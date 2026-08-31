# Hackathon Submission Checklist

## Automated and repository-ready

- [x] Intended user, bottleneck, and value are explicit.
- [x] Direct One-Shot baseline, matched Direct Retry, and advanced BumpShield
  are clearly labeled.
- [x] Improvement changelog records iterations, rationale, evidence, and
  decisions.
- [x] Pre-challenge versus challenge work is disclosed.
- [x] Main failure mode and practical hot take are stated.
- [x] Clean-environment CLI, GUI, baseline, advanced, and evaluation commands
  are documented.
- [x] Tool versions, expected outputs, runtime, provider-call budget, and cost
  limitation are documented.
- [x] Representative development and runtime repair trajectories include tool
  responses, retries, and human checkpoints.
- [x] Frozen benchmark and real-world showcase are clearly separated.
- [x] Credentials, caches, raw provider account data, and cloned upstream source
  are excluded from the archive.
- [x] A deterministic archive builder is included.

## Human actions still required

- [ ] Confirm entrant name, contact information, eligibility, and agreement to
  the Participation Agreement.
- [ ] Decide whether the repository will be public. No project `LICENSE` is
  included; do not imply an open-source grant that has not been selected.
- [ ] Run the final verification commands in `docs/reproduction-guide.md`.
- [ ] Run `python3 scripts/build_submission_archive.py` and retain the printed
  SHA-256 alongside the uploaded file.
- [ ] Upload/publish the repository or sanitized ZIP.
- [ ] Record the video using `docs/video-script.md`; verify it is at most five
  minutes and upload it as public or unlisted.
- [x] Repository URL recorded:
  `https://github.com/FadyYosry77/BumpShield`.
- [ ] Paste the repository and final video URLs into the platform form.
- [ ] Use `docs/submission-form-copy.md` for the remaining form fields and
  replace the video URL placeholder.
- [ ] Attach or link `submission/agent-trajectories/README.md` so every agent
  workflow is reviewable.
- [ ] Submit before **31 August 2026, 18:00 UTC (21:00 Africa/Cairo)**, as stated
  in the supplied challenge rules.

## Final claim check

- [ ] Every quantitative claim links to committed result evidence.
- [ ] The submission says BUMP-FINAL contains 20 synthetic cases and zero real
  project cases.
- [ ] The BoneCP case is labeled a constructed upgrade and excluded from final
  benchmark rates.
- [ ] Provider quota failures remain in strict VRR.
- [ ] No claim says causal analysis improved repair rate on this benchmark.
- [ ] No home path, credential, API key, or private repository appears in the
  upload or video.
