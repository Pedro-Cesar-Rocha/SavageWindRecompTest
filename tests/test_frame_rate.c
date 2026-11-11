// Frame rate choices (settings.h FPS_CHOICES): what Match display picks for a display's refresh rate, and the rate a
// savagewind.ini frame_rate line loads as. argv: the ini, the display's refresh rate (Hz), the frame rate expected
// after loading, and whether Match display is expected on (0 / 1). The ini is saved again after loading (the recipe
// loads it twice: what was saved must load the same).
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include "../runtime/settings.c"
#include "../runtime/hle/bindings.c"

const TextLanguage g_text_languages[] = {{"Auto", NULL, NULL}};
const VoiceLanguage g_voice_languages[] = {{"Auto", NULL}};
const int g_ntext_languages = 1, g_nvoice_languages = 1;
int input_pad_family(void) { return 0; }
bool fsr3_upscaler_enabled(void) { return false; }
static float g_hz;
float winsize_refresh_rate(void) { return g_hz; }

int main(int argc, char **argv) {
    assert(argc == 5);
    setenv("SAVAGEWIND_SETTINGS", argv[1], 1);
    g_hz = (float)atof(argv[2]);
    if (settings_handheld()) {  // (a PC handheld has a list of its own and no Match display)
        puts("SKIP: frame rate choices on a PC handheld");
        return 0;
    }
    const int *list;
    int n = fps_choices(&list);
    bool has75 = false;
    for (int i = 0; i < n; i++) has75 |= list[i] == 75;
    assert(has75 && n <= FPS_CHOICES_MAX);
    // Match display: the display's own rate, rounded, up to 360 (settings_fps_for_display)
    static const struct { float hz; int fps; } match[] = {{59.94f, 60}, {60, 60}, {74.97f, 75}, {75, 75}, {100, 100},
                                                          {144, 144}, {239.77f, 240}, {400, 360}};
    g_settings.fps_display = true;
    for (unsigned i = 0; i < sizeof match / sizeof *match; i++) {
        settings_fps_for_display(match[i].hz);
        if (g_settings.fps_limit != match[i].fps) {
            fprintf(stderr, "FAIL: Match display at %.2f Hz picked %d, expected %d\n", match[i].hz, g_settings.fps_limit,
                    match[i].fps);
            return 1;
        }
    }
    g_settings.fps_display = false;
    g_settings.fps_limit = FPS_DEFAULT;
    settings_load();
    if (g_settings.fps_limit != atoi(argv[3]) || g_settings.fps_display != (atoi(argv[4]) != 0)) {
        fprintf(stderr, "FAIL: loaded frame rate %d (Match display %d), expected %s (%s)\n", g_settings.fps_limit,
                (int)g_settings.fps_display, argv[3], argv[4]);
        return 1;
    }
    settings_save();
    puts("PASS: frame rate choices, Match display and settings load/save");
}
