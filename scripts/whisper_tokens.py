"""Small, versioned patch to the pinned CLI for lossless streaming token data."""
from pathlib import Path

PROTOCOL = 1


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('Pinned whisper.cpp source does not match the token-stream patch')
    return text.replace(old, new, 1)


def patch_whisper(source):
    cli = Path(source) / 'examples/cli/cli.cpp'
    text = cli.read_text(encoding='utf-8')
    if '--substance-tokens' not in text:
        text = replace_once(text, '    bool split_on_word   = false;',
                            '    bool substance_tokens = false;\n    bool split_on_word   = false;')
        text = replace_once(text, '        else if (arg == "-sow"',
                            '        else if (arg == "--substance-tokens") { params.substance_tokens = true; }\n'
                            '        else if (arg == "-sow"')
        text = replace_once(text, '        if (!params.no_timestamps) {\n            printf("[%s --> %s]  ",', '''        if (params.substance_tokens) {
            // Hex preserves BPE byte fragments, including incomplete UTF-8.
            printf("SUBSTANCE_TOKENS {\\"start\\":%lld,\\"end\\":%lld,\\"tokens\\":[",
                   (long long) t0 * 10, (long long) t1 * 10);
            bool first = true;
            for (int j = 0; j < whisper_full_n_tokens(ctx, i); ++j) {
                const auto token = whisper_full_get_token_data(ctx, i, j);
                if (token.id >= whisper_token_eot(ctx)) continue;
                const auto raw = (const unsigned char *) whisper_token_to_str(ctx, token.id);
                printf("%s{\\"hex\\":\\"", first ? "" : ",");
                for (auto p = raw; *p; ++p) printf("%02x", *p);
                printf("\\",\\"start\\":%lld,\\"end\\":%lld,\\"dtw\\":%lld}",
                       (long long) token.t0 * 10, (long long) token.t1 * 10,
                       (long long) token.t_dtw * 10);
                first = false;
            }
            printf("]}\\n");
            fflush(stdout);
            continue;
        }

        if (!params.no_timestamps) {
            printf("[%s --> %s]  ",''')
        cli.write_text(text, encoding='utf-8')

    # Upstream's experimental DTW callback passes segment indices as counts
    # and omits later batches. Emit each completed batch exactly once.
    core = Path(source) / 'src/whisper.cpp'
    text = core.read_text(encoding='utf-8')
    old = '''                        for (int seg = (int) result_all.size() - n_segments; seg < n_segments; seg++) {
                            params.new_segment_callback(ctx, state, seg, params.new_segment_callback_user_data);
                        }'''
    new = '''                        // Substance token stream: one callback per completed DTW batch.
                        params.new_segment_callback(ctx, state, n_segments, params.new_segment_callback_user_data);'''
    if new not in text:
        core.write_text(replace_once(text, old, new), encoding='utf-8')
