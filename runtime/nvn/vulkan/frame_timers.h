#ifndef SW_FRAME_TIMERS_H
#define SW_FRAME_TIMERS_H
#include <stdbool.h>
#include <stdint.h>

// The GPU-timed frame timers (exec.c counter_gpu, SAVAGEWIND_VK_COUNTER=gpu): the GPU's busy time of each presented
// frame from its submissions' begin and end timestamps, and the scale from that time to what the game is told.

typedef struct {
    uint64_t frame;     // the presented frame being added up (UINT64_MAX: none yet)
    uint64_t busy;      // its busy GPU ticks so far
    uint64_t last_end;  // the latest end seen, GPU ticks
} FrameBusy;

#define FRAME_BUSY_INIT {UINT64_MAX, 0, 0}

// A submission of `frame` ran on the GPU from t0 to t1 (ticks), read in submission order. The time it overlaps the
// submissions before it counts once, and a gap between them (the GPU waiting for the CPU) not at all. True when it
// belongs to a later frame than the one added up so far: all of that one's submissions came before, and its busy
// ticks are in *done.
static inline bool frame_busy_note(FrameBusy *fb, uint64_t frame, uint64_t t0, uint64_t t1, uint64_t *done) {
    bool finished = false;
    if (frame != fb->frame) {
        if (fb->frame != UINT64_MAX && frame > fb->frame) {
            *done = fb->busy;
            finished = true;
        }
        fb->frame = frame;
        fb->busy = 0;
    }
    uint64_t from = t0 > fb->last_end ? t0 : fb->last_end;
    if (t1 > from) fb->busy += t1 - from;
    if (t1 > fb->last_end) fb->last_end = t1;
    return finished;
}

// The game's budget is a frame at its interval (1/60 s at interval 1, 1/30 at 2): the GPU's time is scaled by that over
// the period the frames are paced at (period_s), so the budget means the chosen rate (75 fps: x1.25). No limit
// (target 0): 1, the game's own budget. Kept to 0.5..4.
static inline double frame_timer_scale(int target, double period_s, unsigned interval) {
    if (target <= 0 || period_s <= 0 || !interval) return 1.0;
    double k = interval / 60.0 / period_s;
    return k < 0.5 ? 0.5 : k > 4.0 ? 4.0 : k;
}
#endif
