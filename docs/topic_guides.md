# Topic-Specific Teaching Guides

The [Learning Science](learning_science.md) page covers the general model behind
grAIder — feed-forward, mastery levels, calibration, the teacher-in-the-loop.
This page goes one level deeper: for a few recurring CS topics, it summarises the
research and shows a concrete way grAIder's existing features support the
practice. Use it as inspiration when you author criteria (the grAIder Agent Skill
draws on the same guidance when it helps you draft a rubric).

Nothing here is a new feature — each idea maps onto something grAIder already
does: `### Levels` descriptors, staggered criteria, the git-history process
signals, and commit- or prompt-targeted viva questions.

## Test-driven development and test quality

Test-Driven Learning — writing tests alongside or before code — improves
comprehension and design habits, but students are reluctant to work test-first
even after positive experiences ([Test-Driven Learning, SIGCSE](https://dl.acm.org/doi/10.1145/1124706.1121419);
[Test-Driven Learning in Early Programming Courses](https://www.researchgate.net/publication/221537925_Test-Driven_learning_in_early_programming_courses)).
So the *process* deserves to be assessed, not only the final suite. Test-first
behaviour is visible in the history — test files change before or with the source
they cover ([Analyzing the Effects of TDD in GitHub, EMSE](https://softwareprocess.es/pubs/borle2017EMSE-TDD.pdf);
[Process mining of Git logs](https://www.researchgate.net/publication/351459448_Using_process_mining_for_Git_log_analysis_of_projects_in_a_software_development_course)) —
which maps onto grAIder's [process signals](learning_science.md). Coverage alone
is a weak quality measure: criteria should also reward meaningful assertions and
negative/edge cases.

**How grAIder supports it.** Add a *testing process* criterion whose `### Levels`
reward test-first habits and assertion quality, not just a coverage number; the
git-history section of the report shows the commit cadence that reveals whether
tests arrived with the code or were bolted on at the end; a viva `--prompt` can
target a specific test ("why is this the assertion that matters here?").

## Software design and refactoring

Refactoring assessment is subjective and context-dependent — a good fit for
rubric-guided review with a human gate rather than an automated score
([Assessing Refactoring in Education, FIE 2025](https://www.computer.org/csdl/proceedings-article/fie/2025/11328472/2dfa34PmyQw)).
Experienced students reason about quality attributes (coupling, cohesion,
readability) while novices point at surface code
([Student Reasoning in Method-Level Refactoring, Koli Calling](https://dl.acm.org/doi/10.1145/3699538.3699550)),
so design-criterion level descriptors should grade the **quality of the
reasoning**, not just the artifact. Static-analysis findings work well as the
starting point for a "reduce and explain" activity
([AI-Assisted Code Review as a Scaffold](https://arxiv.org/pdf/2604.23251);
[Static Analysis to Engage Students with Quality](https://arxiv.org/pdf/2302.05554)).

**How grAIder supports it.** Write design criteria whose descriptors climb from
"names a problem" → "explains why it is a problem in terms of a quality
attribute" → "justifies the trade-off of the fix"; use the qlty smell counts in
the grade report as the anchor for that conversation; the teacher approval gate
keeps the final judgement human, where subjective design calls belong.

## Algorithm design

The [SOLO taxonomy](https://files.eric.ed.gov/fulltext/EJ1164709.pdf) maps almost
one-to-one onto grAIder's mastery levels: **emerging ≈ unistructural**,
**developing ≈ multistructural**, **proficient ≈ relational**, **exemplary ≈
extended abstract**. The [ACM TOCE review of algorithm-design teaching](https://dl.acm.org/doi/10.1145/3727987)
offers five sub-practices — *use, select, assess, modify, design* algorithms —
that form a ready-made criteria progression. Viva questions should probe the
relational layer: justify the data structure, the complexity, the failure modes.

**How grAIder supports it.** Phrase `### Levels` for an algorithm criterion in
SOLO terms (see the worked example in the Agent Skill); stage the five
sub-practices across milestones with `--up-to`; steer the viva at reasoning with
`--prompt "make them justify the data structure and its complexity"`.

## Debugging

Explicit, systematic debugging instruction reliably improves accuracy,
efficiency, and self-efficacy — yet it is rarely taught directly
([Decoding Debugging Instruction, ACM TOCE](https://dl.acm.org/doi/10.1145/3690652)).
Bug-fix commits are natural viva targets.

**How grAIder supports it.** A *debugging process* criterion can reward a
reproducible-case → hypothesis → fix → regression-test loop; grAIder already
feeds recent commits into the viva, so questions can target a specific bug-fix
commit ("walk me through how you found this one").

## Code comprehension (predict / trace)

Predict-and-trace questions — "what does your function return for input X,
*without running it*?" — are cheap, discriminating comprehension checks, and
tracing-before-writing is a well-supported progression
([PRIMM](https://dl.acm.org/doi/10.1145/3137065.3137084);
[code-tracing research](https://static.teachcomputing.org/pedagogy/QR14-Code-tracing.pdf)).

**How grAIder supports it.** Ask for them in the viva with
`graider interview --prompt "include predict/trace questions: give an input and
ask what the function returns without running it"`.

## Sources

- [Test-Driven Learning: Intrinsic Integration of Testing into the CS/SE Curriculum — SIGCSE](https://dl.acm.org/doi/10.1145/1124706.1121419)
- [Test-Driven Learning in Early Programming Courses](https://www.researchgate.net/publication/221537925_Test-Driven_learning_in_early_programming_courses)
- [Analyzing the Effects of Test-Driven Development in GitHub — EMSE](https://softwareprocess.es/pubs/borle2017EMSE-TDD.pdf)
- [Using Process Mining for Git-Log Analysis of Projects in a Software Development Course](https://www.researchgate.net/publication/351459448_Using_process_mining_for_Git_log_analysis_of_projects_in_a_software_development_course)
- [Assessing Refactoring in Education: A Systematic Literature Review — FIE 2025](https://www.computer.org/csdl/proceedings-article/fie/2025/11328472/2dfa34PmyQw)
- [Investigating Student Reasoning in Method-Level Code Refactoring — Koli Calling](https://dl.acm.org/doi/10.1145/3699538.3699550)
- [AI-Assisted Code Review as a Scaffold for Code Quality and Self-Regulated Learning](https://arxiv.org/pdf/2604.23251)
- [On the Use of Static Analysis to Engage Students with Software Quality Improvement](https://arxiv.org/pdf/2302.05554)
- [Teaching Algorithm Design: A Literature Review — ACM TOCE](https://dl.acm.org/doi/10.1145/3727987)
- [SOLO Taxonomy Applied to Algorithmic Problems](https://files.eric.ed.gov/fulltext/EJ1164709.pdf)
- [Decoding Debugging Instruction: A Systematic Literature Review — ACM TOCE](https://dl.acm.org/doi/10.1145/3690652)
- [PRIMM: Exploring Pedagogical Approaches for Teaching Text-Based Programming](https://dl.acm.org/doi/10.1145/3137065.3137084)
- [Code-Tracing Research (Tracing Before Writing)](https://static.teachcomputing.org/pedagogy/QR14-Code-tracing.pdf)
