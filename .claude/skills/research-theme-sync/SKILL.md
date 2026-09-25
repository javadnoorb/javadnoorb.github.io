---
name: research-theme-sync
description: Re-derive Javad Noorbakhsh's research themes and technical skills directly from his publication record (data/publications.json), to keep data/profile.yaml's research_focus and skills sections evidence-based instead of generic. Use when publications have changed significantly, when asked to review/update research focus or skills, or periodically as the publication list grows.
---

# Deriving research themes and skills from publications

`data/profile.yaml`'s `research_focus` section (shown on the homepage) and
`skills` section exist to make claims a reader can verify against actual
work, not generic resume buzzwords. This skill is the repeatable method for
re-deriving them from `data/publications.json` as the publication record
changes. See the `personal-site` skill for the repo's general architecture
and deploy workflow - this one is just about the analysis.

## Paper notes

`~/research-papers/notes.md` (outside this repo, alongside the downloaded
PDFs) is a running log of what's been read/extracted from each paper -
key findings in plain English, which figure was chosen for the Research
Highlights page and its exact crop coordinates, and authorship status
(Research Highlights only features first-author work - see "Content
guidelines" in the `personal-site` skill). Check it before re-reading a
paper from scratch, and append to it as you read new ones.

## Method

1. **Read every publication, don't keyword-match blindly.** Load
   `data/publications.json` and actually read each title + venue + year +
   citation count. Titles are often too terse or jargon-heavy for naive
   keyword extraction to cluster correctly (e.g. "Repeat expansions confer
   WRN dependence in microsatellite-unstable cancers" is a cancer-genomics
   paper, not an obviously-labeled one).

2. **Cluster by actual methodology/domain, weighted toward sequence, not
   just topic.** Look at how the themes evolve across years - career
   narratives usually show a progression (e.g. this user's record shows
   quantitative/biophysics work in 2013-2015 during their Physics PhD,
   shifting to cancer genomics/tumor evolution around 2017-2020, then to
   AI/deep learning for computational pathology and spatial omics from
   2020 onward, which is also their current job). A narrative arc is more
   useful on a homepage than a flat list of unordered topics.

3. **Weight by citation count and venue, not just count of papers.** A
   cluster's flagship paper (highest citations, most prominent venue) is
   what should anchor that cluster's description. Don't let a thematic
   bucket with one 4-citation preprint get equal billing to one anchored by
   a 600+ citation *Nature* paper.

4. **Cross-check against `data/profile.yaml`'s `experience` bullets** for
   consistency. The job history is independent evidence: if a theme shows
   up strongly in both publications and job bullets, it's a safe, well-
   supported claim. If publications suggest a skill/theme that's absent
   from experience (or vice versa), that's worth surfacing to the user
   rather than silently resolving - they may have deliberately left
   something out (see `personal-site` skill's content guidelines - e.g.
   they explicitly don't want a grants section even though "grant
   proposals" appears in a bullet).

5. **Distinguish "evidenced by publications" from "true but unpublished"
   skills.** Software/infrastructure skills (Kubernetes, cloud computing,
   version control) usually won't show up in publication titles at all -
   that's expected and not a contradiction. Don't remove or flag those.
   Only flag a genuine mismatch: e.g. a technique used repeatedly across
   several papers (spatial transcriptomics, graph neural networks, foundation
   models) that isn't reflected anywhere in the skills list.

6. **Propose, don't silently overwrite.** `research_focus` and `skills` are
   read by recruiters as the user's own voice/claims. Present the derived
   themes and any suggested skill additions to the user for approval before
   editing `profile.yaml`, the same way you'd preview any other content
   change on this site before pushing.

## Worked example (as of the 24-publication corpus analyzed 2026-09)

Three clusters emerged, in this order of career progression:

- **Systems biology & biophysics** (2013-2015): quantitative modeling of
  cellular signaling oscillations and gene-regulatory noise - anchored by
  a 104-citation *Molecular Systems Biology* paper.
- **Cancer genomics & tumor evolution** (2017-2024): tumor heterogeneity,
  subclonal dynamics, evolutionary pressure - anchored by two flagship
  *Nature* papers (649 and 229 citations).
- **AI for computational pathology & spatial omics** (2020-present): deep
  learning on histopathology images and spatial omics data - this is the
  user's current role's focus, anchored by a 243-citation *Nature
  Communications* paper.

This is written into `data/profile.yaml`'s `research_focus` field. **Don't
treat this three-cluster breakdown as permanent** - re-derive it (following
the method above) whenever the publication list changes meaningfully (a
handful of new papers, especially in a new area, is enough to warrant
re-checking), rather than assuming it still holds.
