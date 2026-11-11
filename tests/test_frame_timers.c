// The GPU-timed frame timers (runtime/nvn/vulkan/frame_timers.h): busy time per presented frame from submission
// timestamps, and the scale to the game's budget. Synthetic timestamps only.
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include "../runtime/nvn/vulkan/frame_timers.h"

static bool near(double a, double b) { return fabs(a - b) < 1e-9; }

int main(void) {
    FrameBusy fb = FRAME_BUSY_INIT;
    uint64_t done = 0;
    // Frame 1: three submissions, one gap (100..150: the GPU waited for the CPU) and one overlap (280..300).
    assert(!frame_busy_note(&fb, 1, 0, 100, &done));
    assert(!frame_busy_note(&fb, 1, 150, 300, &done));
    assert(!frame_busy_note(&fb, 1, 280, 400, &done));
    assert(fb.busy == 100 + 150 + 100);
    // Frame 2's first submission: frame 1 is all read.
    assert(frame_busy_note(&fb, 2, 420, 500, &done) && done == 350);
    // One that began before the last end (the GPU still on the one before) and ended before it: nothing more.
    assert(!frame_busy_note(&fb, 2, 450, 480, &done) && fb.busy == 80);
    // A frame with no submission of its own read (2 -> 4): the one before is reported, the missing one isn't.
    assert(frame_busy_note(&fb, 4, 600, 610, &done) && done == 80);
    // An empty or reversed interval adds nothing.
    assert(!frame_busy_note(&fb, 4, 700, 700, &done) && fb.busy == 10);
    // An older frame's submission (never in practice) starts that frame over without reporting.
    assert(!frame_busy_note(&fb, 3, 800, 900, &done) && fb.frame == 3 && fb.busy == 100);

    // Scale: the game's budget (its interval at 60 per second) over the paced period.
    assert(near(frame_timer_scale(60, 1 / 60.0, 1), 1.0));
    assert(near(frame_timer_scale(75, 1 / 75.0, 1), 1.25));
    assert(near(frame_timer_scale(30, 1 / 30.0, 2), 1.0));
    assert(near(frame_timer_scale(120, 1 / 120.0, 1), 2.0));
    // VSync's cap under a 75 Hz display's refresh (75 - 75^2 / 3600 fps)
    assert(near(frame_timer_scale(75, 1 / (75 - 75.0 * 75 / 3600), 1), (75 - 75.0 * 75 / 3600) / 60));
    // Frame generation paces the game's frames at twice the period: the game's own rate counts
    assert(near(frame_timer_scale(120, 2 / 120.0, 1), 1.0));
    assert(near(frame_timer_scale(0, 1 / 360.0, 1), 1.0));   // no limit: the game's own budget
    assert(near(frame_timer_scale(360, 1 / 360.0, 1), 4.0));  // kept to 4
    assert(near(frame_timer_scale(30, 1 / 30.0, 1), 0.5));    // (the interval still at 1, just after a change)
    assert(near(frame_timer_scale(20, 1 / 20.0, 1), 0.5));    // kept to 0.5
    assert(near(frame_timer_scale(60, 0, 1), 1.0) && near(frame_timer_scale(60, 1 / 60.0, 0), 1.0));
    puts("Frame timers: PASS (gameplay validation pending)");
}
