# Syntax Reference — Script Dubbing

> Applies to the Script Dubbing node (IndexTTSLocalScriptDubbing). This page only covers how to write the script; install and parameters live in the README.

## 1. Segment markers

~~~text
[@R0]           role #1, keep the reference voice's own emotion
[@R1:raging]    role #2 + a specified emotion
~~~

| Rule | Meaning |
|---|---|
| Must start at column 0 | The very first character must be `[`; leading spaces, tabs or full-width spaces disqualify it |
| Only at the start of a line | A mid-line `[` is plain text and will be spoken out |
| Segment extent | From one marker up to the next marker; newlines do not end a segment |
| Preamble | Text before the first marker is treated as `[@R0]` |
| No markers at all | The whole script becomes one segment, one request |
| Text is kept as written | No strip, no merging, no substitution (the space after `]` and inner newlines are preserved) |

## 2. Roles

~~~text
R0 = the 1st audio wired into ref_audio
R1 = the 2nd
R2 = the 3rd …
~~~

- Case-insensitive: `[@r1]` is the same as `[@R1]`
- Leading zeros allowed: `[@R01]` is the same as `[@R1]`
- Out of range wraps around: `R10` → built-in role 1, `R13` → built-in role 4
- Unconnected roles fall back to built-in voices (R0 female and R1 male ship with the plugin; R2–R9 download on first use)

## 3. Three ways to write the emotion field

### 3.1 Labels (become an 8-dim vector)

~~~text
[@R0:happy]               single label, weight defaults to 1.0
[@R0:happy0.7]            with weight (the number follows the label, 0–1)
[@R0:happy0.7+surprised0.2]   several labels joined with +
[@R0:happy+surprised]     no weights = 1.0 each
~~~

### 3.2 Free description (handed to QwenEmotion)

~~~text
[@R0:raging and hoarse]
[@R0:calm and patient]
[@R0:on the verge of tears]
~~~

> Requires the WebUI to be started with `--qwen_emo`, otherwise you get `NO_QWEN_EMOTION`.

### 3.3 Follow (no emotion control)

~~~text
[@R0]       no colon
[@R0:]      empty after the colon
[@R0:follow]   explicit
~~~

Decision rule: the field is treated as labels **only when the whole string consists of labels, optional numbers and plus signs**; anything else is a free description.

## 4. Emotion labels

| Dimension | Chinese | English |
|---|---|---|
| 1 | 开心 / 高兴 | happy |
| 2 | 愤怒 / 生气 | angry |
| 3 | 悲伤 | sad |
| 4 | 害怕 / 恐惧 | afraid |
| 5 | 厌恶 | disgusted |
| 6 | 低落 / 忧郁 | melancholic / melancholy |
| 7 | 惊讶 | surprised |
| 8 | 平静 / 自然 | calm |

## 5. Weights and effective strength

~~~text
the weight you write
  × upstream bias (happy 0.9375 / angry 0.875 / sad 1.0 / afraid 1.0
                   disgusted 0.9375 / melancholic 0.9375 / surprised 0.6875 / calm 0.5625)
  × node parameter emo_weight (0.65 by default, adjustable on the node)
  = the value that actually reaches the model
~~~

| Marker | After bias | × 0.65 | Effective |
|---|---|---|---|
| `happy0.5` | 0.469 | 0.305 | 0.305 |
| `happy0.7` | 0.656 | 0.427 | 0.427 |
| `happy1.0` | 0.938 | 0.609 | 0.609 |

- If the eight dimensions add up to more than 0.8, the upstream scales them all down
- To make "write 0.7 get 0.7", set `emo_weight` to 1.0 on the node

## 6. Complete example

~~~text
I worked three years, and today I finally slammed the resignation letter on the desk.

[@R1:raging] You still don't get me!

[@R0:calm0.8] Really? Nice weather today.

[@R1:angry0.9+sad0.3]
I pulled how many all-nighters,
and one "change it again" threw it all away.
~~~

> Want a sample that covers every feature? See [example-script.md](example-script.md).

## 7. Errors and warnings

**Errors (the run fails)**

| Code | Meaning |
|---|---|
| MARKER_UNCLOSED | `[@R0` is missing the closing bracket |
| INVALID_ROLE | Bad role number (`[@Rab]`, `[@R1.5]`) |
| EQ_SYNTAX | Written as `happy=0.8` (use `happy0.8`) |
| WEIGHT_RANGE | Weight below 0 or above 1 |
| EMPTY_TEXT | Nothing to synthesize |
| NO_QWEN_EMOTION | Free description used but the server has no QwenEmotion |

**Warnings (the run continues)**

| Code | Meaning |
|---|---|
| INDENT:line | Looks like a marker but is not at column 0, treated as text |
| FULLWIDTH:line | Line starts with a full-width bracket, treated as text |
| WHITESPACE_ONLY:line | Only whitespace after the marker, treated as an empty segment |
| SUM_OVER_0.8 | Several labels without weights, the sum will be compressed |

## 8. FAQ

**Can I use newlines as pauses?**
No. Newlines are layout only and the server turns them into spaces. Use the `gap_ms` parameter, or split the line into separate segments.

**Why are subtitles limited to the segment level?**
IndexTTS returns no word-level alignment, so subtitle granularity equals marker granularity. Want one subtitle per sentence? Put each sentence in its own segment.

**What triggers a re-synthesis?**
Changing the segment text, role audio, emotion, `duration_factor` or `emo_weight` re-synthesizes; changing `gap_ms`, `intro_ms` or `subtitle_format` only re-merges and re-renders subtitles.

**Why is the second run so fast?**
Segment audio is cached per seed under output/indextts-cache/<seed>/; unchanged content is reused. Change the seed for a fresh take.
