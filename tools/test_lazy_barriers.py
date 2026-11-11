#!/usr/bin/env python3
"""The pass barrier decisions of runtime/nvn/vulkan/exec.c (lazy_barriers), taken from the source and run on synthetic
passes and draws: which passes begin without a barrier, which draws make one first, what is marked read and drawn."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "runtime/nvn/vulkan/exec.c").read_text()


def cut(start, end):
    a = source.index(start)
    return source[a:source.index(end, a)]


state = cut("static uint32_t lb_epoch = 1;", "// Pass barriers (begin_pass, SAVAGEWIND_VK_BARRIER_FRAG)")
full = cut("// Pass barriers (begin_pass, SAVAGEWIND_VK_BARRIER_FRAG)", "static void pass_barrier(VkCommandBuffer cb) {")
targets = cut("// (lazy_barriers) the image of attachment t was drawn into", "static void begin_pass(void) {")
draws = cut("static uint32_t lb_draw_epoch;", "static TexBackend *snapshot_image(")

fixture = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define LOG printf
typedef struct VkCommandBuffer_T *VkCommandBuffer;
typedef struct { int sType; uint64_t srcStageMask, srcAccessMask, dstStageMask, dstAccessMask; } VkMemoryBarrier2;
typedef struct { int sType; uint32_t memoryBarrierCount; const VkMemoryBarrier2 *pMemoryBarriers; } VkDependencyInfo;
enum { VK_STRUCTURE_TYPE_MEMORY_BARRIER_2 = 1, VK_STRUCTURE_TYPE_DEPENDENCY_INFO = 2 };
enum { VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT = 1, VK_ACCESS_2_MEMORY_WRITE_BIT = 1, VK_ACCESS_2_MEMORY_READ_BIT = 2 };
static void rec_CmdPipelineBarrier2(VkCommandBuffer cb, const VkDependencyInfo *di) { (void)cb; (void)di; }
#define MAIN ((VkCommandBuffer)(uintptr_t)1)
#define UPLOAD ((VkCommandBuffer)(uintptr_t)2)
static struct { VkCommandBuffer main, upload; } subs[1] = {{MAIN, UPLOAD}};
static int cur_sub;
typedef struct { void *image; uint32_t lb_drawn, lb_read; } TexBackend;
typedef struct { TexBackend *backend; } NvnTexture;
typedef struct { bool shadow, is_image; int slot; } ShaderTexture;
typedef struct { int ntex; ShaderTexture tex[8]; bool writes_gmem; } ShaderInfo;
typedef struct { ShaderInfo *vi, *fi; } Prog;
static struct { bool is_mali; } g_vk;
static struct { struct { int ncolor; NvnTexture *color[8]; NvnTexture *depth; } rt; bool rt_dirty; } st;
static bool in_pass, bar_other = true;  // (as in exec.c: the first pass begins behind a full barrier)
static int bar_n;
static int ends;
static NvnTexture *bound[2][8];  // (stage, slot): the texture a shader texture reads
static NvnTexture *shader_texture_object(int sg, ShaderTexture *te) { return bound[sg][te->slot]; }
static NvnTexture *shadow_copy_source(NvnTexture *t) { (void)t; return NULL; }
static TexBackend *vk_tex_peek(const NvnTexture *t) { return t ? t->backend : NULL; }
static void vk_end_pass(void) { in_pass = false; ends++; }
static TexBackend *mvec_target_img;  // (the motion target: Video > Anti-aliasing TAA)
static bool mvec_on;
static bool mvec_enabled(void) { return mvec_on; }
"""

harness = r"""
// begin_pass's barrier decision and its bookkeeping (the attachments noted after it)
static int barriers;
static void pass_barrier_note(TexBackend *b) { b->lb_drawn = lb_epoch; bar_n++; }
static void barrier(void) {  // (pass_barrier: a full one after other work, else one for the passes' targets)
    barriers++;
    if (bar_other) { vk_full_barrier(MAIN); bar_other = false; return; }
    bar_n = 0;
    lb_reset();
}
static void begin(void) {
    if (in_pass && !st.rt_dirty) return;
    if (lazy_barriers() && !bar_other && !lb_force && !lb_targets_busy()) { stat_lazy_skipped++; lb_open = true; }
    else { barrier(); lb_open = false; }
    lb_passes++;
    st.rt_dirty = false;
    for (int i = 0; i < st.rt.ncolor; i++) pass_barrier_note(st.rt.color[i]->backend);
    if (st.rt.depth) pass_barrier_note(st.rt.depth->backend);
    if (st.rt.depth && mvec_target_img && mvec_enabled()) pass_barrier_note(mvec_target_img);
    in_pass = true;
}
static void targets(NvnTexture *c, NvnTexture *d) {
    st.rt.ncolor = c ? 1 : 0;
    st.rt.color[0] = c;
    st.rt.depth = d;
    st.rt_dirty = true;
}
static void draw(Prog *pr) {
    lb_draw(pr);
    begin();
    lb_draw_after(pr);
    if (pr->vi->writes_gmem || pr->fi->writes_gmem) bar_other = true;  // (gw_note)
}

#define TEX(name) static TexBackend name##_b = {(void *)&name##_b}; static NvnTexture name = {&name##_b}
TEX(A); TEX(B); TEX(C); TEX(D); TEX(E); TEX(F); TEX(G); TEX(H); TEX(I); TEX(J); TEX(K); TEX(L); TEX(M); TEX(Z);

int main(void) {
    ShaderInfo none = {0}, samples_a = {1, {{false, false, 0}}}, stores = {0, {{0}}, true}, image = {1, {{false, true, 1}}};
    Prog plain = {&none, &none}, read_a = {&none, &samples_a}, store = {&none, &stores}, imgs = {&none, &image};
    bound[1][0] = &A;
    bound[1][1] = &Z;

    // a pass into A behind a barrier (nothing known before it), then one into B that doesn't read A: no barrier
    targets(&A, NULL); draw(&plain);
    assert(barriers == 1 && stat_lazy_skipped == 0);
    targets(&B, NULL); draw(&plain);
    assert(barriers == 1 && stat_lazy_skipped == 1 && lb_open);
    // a draw of B's pass that samples A: the pass ends, the barrier comes, the pass begins again
    draw(&read_a);
    assert(barriers == 2 && stat_lazy_restarts == 1 && ends == 1 && !lb_open);
    assert(A_b.lb_read == lb_epoch);  // (read again in the new epoch: a pass into A after this waits for it)
    // a pass into A now: A was sampled since that barrier (write after read): behind a barrier
    targets(&A, NULL); draw(&plain);
    assert(barriers == 3);
    // a pass into C whose first draw samples A, just drawn: the barrier before it, no restart
    targets(&C, NULL); draw(&read_a);
    assert(barriers == 4 && stat_lazy_restarts == 1);
    // the same depth again (drawn into since the last barrier): behind a barrier
    targets(&D, &E); draw(&plain);
    assert(barriers == 4);  // (D and E are new: skipped)
    targets(&C, &E); draw(&plain);
    assert(barriers == 5);
    // a draw sampling its own target (resolve_feedback's case) makes no barrier
    bound[1][0] = &C;
    draw(&read_a);
    assert(barriers == 5 && stat_lazy_restarts == 1);
    bound[1][0] = &A;
    // a pass that reads nothing new, then a draw in it that stores to memory: barrier first (earlier passes may read it)
    targets(&D, NULL); draw(&plain);
    int skipped = (int)stat_lazy_skipped;
    assert(lb_open);
    draw(&store);
    assert(barriers == 6 && stat_lazy_restarts == 2 && !lb_open && stat_lazy_skipped == (uint64_t)skipped);
    // another store in the same pass, now behind the barrier: nothing more
    draw(&store);
    assert(barriers == 6);
    // a storage image: barrier first if needed, and the passes after it behind a full barrier (bar_other)
    targets(&B, NULL); draw(&imgs);
    assert(barriers == 7 && bar_other);
    targets(&E, NULL); draw(&plain);  // (E: nothing of it since the barrier, but the image stores before it)
    assert(barriers == 8 && !bar_other);
    // a pass after only a barrier, into what nothing touched since: no barrier; its draw reading A (drawn long before,
    // behind barriers since): none either
    targets(&Z, NULL); draw(&read_a);
    assert(barriers == 8 && lb_open);

    // a texture uploaded while a pass that began without a barrier is open: the upload buffer's barrier runs before
    // the whole main buffer, so the passes before this one are not behind it - a draw reading one's target still
    // ends the pass for a barrier
    vk_end_pass();
    vk_full_barrier(MAIN);  // (a copy, say: the next pass begins behind a full barrier)
    targets(&F, NULL); draw(&plain);
    assert(barriers == 9);
    targets(&G, NULL); draw(&plain);
    assert(barriers == 9 && lb_open);
    vk_full_barrier(UPLOAD);
    assert(!bar_other && bar_n == 2);
    bound[1][0] = &F;
    draw(&read_a);
    assert(barriers == 10 && stat_lazy_restarts == 3);
    bound[1][0] = &A;
    // ... and a store in such a pass too
    targets(&H, NULL); draw(&plain);
    assert(barriers == 10 && lb_open);
    vk_full_barrier(UPLOAD);
    draw(&store);
    assert(barriers == 11 && stat_lazy_restarts == 4);

    // the motion target (Video > Anti-aliasing TAA), which every pass with the scene depth draws into as well: of two
    // such passes the second begins behind a barrier, though its own targets are new; one without depth doesn't
    mvec_on = true;
    mvec_target_img = &M_b;
    targets(&I, &J); draw(&plain);  // (after the store: a full barrier anyway)
    assert(barriers == 12);
    targets(&K, &L); draw(&plain);
    assert(barriers == 13);
    targets(&D, NULL); draw(&plain);
    assert(barriers == 13 && lb_open);
    mvec_on = false;

    // a submission ends (the closing barrier of its upload buffer): the pass after it is judged as any other - into
    // what nothing touched since the last barrier, without one; one whose draw reads what a pass before drew, behind it
    vk_end_pass();
    vk_full_barrier(UPLOAD);
    assert(!bar_other);
    targets(&E, NULL); draw(&plain);
    assert(barriers == 13 && lb_open);
    bound[1][0] = &K;
    targets(&F, NULL); draw(&read_a);
    assert(barriers == 14);
    bound[1][0] = &A;
    puts("lazy pass barriers: passed");
    return 0;
}
"""

with tempfile.TemporaryDirectory() as d:
    src = os.path.join(d, "t.c")
    exe = os.path.join(d, "t")
    with open(src, "w") as f:
        f.write(fixture + state + full + targets + draws + harness)
    cc = shutil.which("clang") or shutil.which("cc")
    subprocess.run([cc, "-std=gnu11", "-Wall", "-Wno-unused-function", "-Wno-unused-variable", "-o", exe, src], check=True)
    for env in ({}, {"SAVAGEWIND_VK_LAZY_BARRIERS": "1"}):
        subprocess.run([exe], check=True, env={**os.environ, **env})
