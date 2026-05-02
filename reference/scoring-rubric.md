# StoryForge Scoring Rubric

## Mechanical Scoring (Draft Phase - Gemini Flash)

### Banned Words
Each occurrence of a banned word incurs -0.5 penalty (capped at -5.0 total).
Banned list: suddenly, very, quite, literally, actually, basically, gaze, smirk, chuckle, sigh, nod, shrug, and ~30 more (see config.py).

### Show-Don't-Tell Ratio
Count of "telling" patterns (felt that, knew that, realized that, it was X that, there was/were) divided by total sentences.
Threshold: 0.3. Above this, subtracts (ratio - threshold) x 3 from base score.

### Pacing Variance
Standard deviation of sentence lengths (in words). Higher = more varied rhythm.
Normalized to 0-1 range: min(std_dev/10, 1). Adds std_dev x 0.5 to score.

### Dialogue Ratio
Dialogue lines / word count. Monitors for balanced prose vs dialogue.
Not scored directly - reported for author awareness.

### Base Score
Starts at 7.0/10. Modified by penalties and bonuses above.

## LLM Judge Scoring (Review Phase - Kimi K2.6)

### Prose Score (0-10)
Sentence craft, imagery, metaphor quality, rhythm, vocabulary precision.

### Pacing Score (0-10)
Tension, momentum, scene structure, chapter-level arc, paragraph flow.

### Character Score (0-10)
Depth, voice consistency, interiority, motivation clarity, growth signals.

### Dialogue Score (0-10)
Naturalness, subtext, characterization through speech, rhythm, differentiation between speakers.

### Structure Score (0-10)
Scene architecture, chapter arc (beginning-middle-end), hook, cliffhanger management.

### Overall Score (0-10)
Holistic judgment combining all dimensions.

## Revision Thresholds
- Min acceptable: 6.0/10
- Target: 8.0/10
- Max revision rounds per chapter: 3
- Max full-manuscript review rounds: 5
