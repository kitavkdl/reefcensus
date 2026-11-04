/* SAM 3.1 "one_bit" mask decoder: a C port of meta_sam_parser._mask_codec._unpack + _decode_raster.
   The reference is pure Python and costs ~0.3 s a mask (the parser decodes, re-encodes to check, and
   decode_mask_to_raster does both again); this does one decode in ~1 ms. Built on first use by maskcodec.py.
   Returns 0, or a negative code on a malformed payload (the caller falls back to the reference decoder).
   As a port of meta_sam_parser (SAM Materials), this file is distributed under the SAM License; a copy is in
   fishcount/LICENSE-SAM. */
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define RADIX 85
#define PREFIX 5
#define TOP (1u << 24)
#define BOTTOM (1u << 16)
#define INCREMENT 14
#define COUNT_LIMIT 4096
#define CONTEXTS (1 << 12)
#define PAD 2

static int digit_of[128];
static int ready;

static void init(void) {
    const char *excluded = "\"\\,;<>|";
    int i = 0;
    for (int c = 0; c < 128; c++) digit_of[c] = -1;
    for (int c = 0x21; c < 0x7f; c++)
        if (!strchr(excluded, c)) digit_of[c] = i++;
    ready = 1;
}

static int digit(unsigned char c) {
    int v = c < 128 ? digit_of[c] : -1;
    return v < 0 || v >= RADIX ? -1 : v;
}

/* Base-85 with a 5-digit length prefix; tail group padded with the top digit. */
static int64_t unpack(const char *s, int64_t n, uint8_t **out) {
    if (n < PREFIX) return -1;
    int64_t len = 0;
    for (int i = 0; i < PREFIX; i++) {
        int d = digit(s[i]);
        if (d < 0) return -2;
        len = len * RADIX + d;
    }
    int64_t rem = len % 4;
    if (n != PREFIX + (len / 4) * 5 + (rem ? rem + 1 : 0)) return -3;
    uint8_t *o = malloc(len ? len : 1);
    if (!o) return -9;
    int64_t src = PREFIX, dst = 0, full = len - rem;
    while (dst < full) {
        uint64_t v = 0;
        for (int i = 0; i < 5; i++) {
            int d = digit(s[src + i]);
            if (d < 0) { free(o); return -2; }
            v = v * RADIX + d;
        }
        if (v > 0xFFFFFFFFull) { free(o); return -4; }
        src += 5;
        o[dst] = v >> 24; o[dst + 1] = v >> 16; o[dst + 2] = v >> 8; o[dst + 3] = v;
        dst += 4;
    }
    if (rem) {
        uint64_t v = 0;
        for (int i = 0; i < 5; i++) {
            int d = i < rem + 1 ? digit(s[src + i]) : RADIX - 1;
            if (d < 0) { free(o); return -2; }
            v = v * RADIX + d;
        }
        if (v > 0xFFFFFFFFull) { free(o); return -4; }
        for (int i = 0; i < rem; i++) o[dst + i] = v >> (24 - i * 8);
    }
    *out = o;
    return len;
}

int decode_one_bit(const char *payload, int64_t plen, int width, int height, uint8_t *out) {
    if (!ready) init();
    if (width <= 0 || height <= 0) return -5;
    uint8_t *in;
    int64_t n = unpack(payload, plen, &in);
    if (n < 0) return (int)n;
    if (n < 4) { free(in); return -6; }
    int64_t pos = 0;
    uint32_t low = 0, range = 0xFFFFFFFFu, code = 0;
    for (int i = 0; i < 4; i++) code = (code << 8) | in[pos++];

    static __thread uint16_t counts[CONTEXTS * 2];
    for (int i = 0; i < CONTEXTS * 2; i++) counts[i] = 1;
    int pw = width + 2 * PAD;
    uint8_t *padded = calloc((size_t)pw * (height + PAD), 1);
    if (!padded) { free(in); return -9; }
    int rc = 0;
    for (int y = 0; y < height && !rc; y++) {
        int row = (y + PAD) * pw + PAD;
        for (int x = 0; x < width; x++) {
            int p = row + x, q = p - pw, e = p - 2 * pw;
            int ctx = padded[p - 1] | padded[p - 2] << 1 | padded[q - 2] << 2 | padded[q - 1] << 3 | padded[q] << 4
                    | padded[q + 1] << 5 | padded[q + 2] << 6 | padded[e - 2] << 7 | padded[e - 1] << 8 | padded[e] << 9
                    | padded[e + 1] << 10 | padded[e + 2] << 11;
            int off = ctx << 1;
            uint32_t zero = counts[off], one = counts[off + 1], total = zero + one;
            uint32_t scaled = range / total;
            if (!scaled) { rc = -7; break; }
            uint32_t v = (code - low) / scaled;
            if (v >= total) v = total - 1;
            int bit = v < zero ? 0 : 1;
            uint32_t cum = bit ? zero : 0, freq = bit ? one : zero;
            low += scaled * cum;
            range = scaled * freq;
            for (;;) {
                if ((low ^ (low + range)) < TOP) {
                } else if (range < BOTTOM) {
                    range = (0u - low) & (BOTTOM - 1);
                } else break;
                if (pos >= n) { rc = -8; break; }
                code = (code << 8) | in[pos++];
                low <<= 8;
                range <<= 8;
            }
            if (rc) break;
            padded[p] = bit;
            out[(int64_t)y * width + x] = bit;
            counts[off + bit] += INCREMENT;
            if (counts[off] + counts[off + 1] >= COUNT_LIMIT) {
                counts[off] = (counts[off] >> 1) ? counts[off] >> 1 : 1;
                counts[off + 1] = (counts[off + 1] >> 1) ? counts[off + 1] >> 1 : 1;
            }
        }
    }
    free(padded);
    free(in);
    return rc;
}
