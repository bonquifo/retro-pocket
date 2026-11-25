/*
 * LD_PRELOAD shim for desmume-cli 0.9.13 keyboard input.
 *
 * Its frontend memcpy()s the 32-bit default key table into a 16-bit array,
 * so most keyboard bindings are scrambled (Down closes the lid; B, Start,
 * L and Y are unreachable) and its config file is ignored. The joystick
 * table is intact, so translate Retro Pocket's layout into joystick events
 * on device 0. Other keys pass through unchanged.
 *
 * RETRO_POCKET_DS_KEYMAP="sym:target,..." where target is bN (button N),
 * x+, x-, y+ or y- (axis 0/1). No SDL headers: SDL2's stable event ABI.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

enum { KEYDOWN = 0x300, KEYUP = 0x301, JOYAXIS = 0x600, JOYBUTTONDOWN = 0x603, JOYBUTTONUP = 0x604 };
enum { MAX_KEYS = 32 };

struct binding { int32_t sym; char kind; int index; int sign; };
static struct binding bindings[MAX_KEYS];
static int count = -1;
static int held[2][2];  /* [axis][negative, positive] */

static void load_bindings(void) {
    const char *spec = getenv("RETRO_POCKET_DS_KEYMAP");
    count = 0;
    while (spec && *spec && count < MAX_KEYS) {
        char *end;
        long sym = strtol(spec, &end, 10);
        if (end == spec || *end != ':')
            return;
        struct binding b = { (int32_t)sym, end[1], 0, 0 };
        if (b.kind == 'b') {
            b.index = (int)strtol(end + 2, &end, 10);
            if (b.index < 0 || b.index > 31)
                return;
        } else if ((b.kind == 'x' || b.kind == 'y') && (end[2] == '+' || end[2] == '-')) {
            b.index = b.kind == 'y';
            b.sign = end[2] == '+' ? 1 : 0;
            end += 3;
        } else {
            return;
        }
        bindings[count++] = b;
        if (*end != ',')
            return;
        spec = end + 1;
    }
}

/* Rewrite one SDL_Event in place; exported for tests. Returns 1 if changed. */
int rp_ds_translate(unsigned char *event) {
    uint32_t type;
    int32_t sym;
    memcpy(&type, event, 4);
    if (type != KEYDOWN && type != KEYUP)
        return 0;
    if (count < 0)
        load_bindings();
    memcpy(&sym, event + 20, 4);
    for (int i = 0; i < count; i++) {
        const struct binding *b = &bindings[i];
        if (b->sym != sym)
            continue;
        int pressed = type == KEYDOWN;
        unsigned char timestamp[4];
        memcpy(timestamp, event + 4, 4);
        memset(event, 0, 56);  /* sizeof(SDL_Event) */
        memcpy(event + 4, timestamp, 4);  /* which (offset 8) stays 0 */
        if (b->kind == 'b') {
            type = pressed ? JOYBUTTONDOWN : JOYBUTTONUP;
            event[12] = (unsigned char)b->index;
            event[13] = (unsigned char)pressed;
        } else {
            /* Keep the opposite direction if it is still held. */
            held[b->index][b->sign] = pressed;
            int16_t value = held[b->index][b->sign] ? (b->sign ? 32767 : -32767)
                          : held[b->index][!b->sign] ? (b->sign ? -32767 : 32767) : 0;
            type = JOYAXIS;
            event[12] = (unsigned char)b->index;
            memcpy(event + 16, &value, 2);
        }
        memcpy(event, &type, 4);
        return 1;
    }
    return 0;
}

int SDL_PollEvent(void *event) {
    static int (*real)(void *);
    if (!real)
        real = (int (*)(void *))dlsym(RTLD_NEXT, "SDL_PollEvent");
    int result = real(event);
    if (result == 1 && event)
        rp_ds_translate(event);
    return result;
}

int SDL_WaitEvent(void *event) {
    static int (*real)(void *);
    if (!real)
        real = (int (*)(void *))dlsym(RTLD_NEXT, "SDL_WaitEvent");
    int result = real(event);
    if (result == 1 && event)
        rp_ds_translate(event);
    return result;
}
