# Reviewer Evidence Capture

## Purpose

This procedure captures human review evidence for the selected evaluation cases without placing candidate output, reviewer packets, labels, or reviewer identity details in the Git repository.

The repository contains the evaluation-case fixture, the rubric, source fixtures, code, and packet-generation command. A review packet is a content-bearing artifact kept outside the repository. A database review label stores only immutable hashes that bind the label to its packet.

No reviewer output is created by this procedure. A completed packet and label are evidence only when supplied by the named human reviewer.

## Trust boundaries

- Evaluation-run and B1 reference artifacts remain content-free.
- Primary packets contain the case request, verified source snapshots, and the exact candidate output under review.
- Independent packets contain the case request and verified source snapshots. They exclude candidate output, primary labels, adjudication material, and ground truth.
- Ground truth is never supplied to either reviewer.
- Every source snapshot is verified against the SHA-256 declared by the evaluation case before the packet is written.
- Packets must be written outside the repository root. Do not add them to Git.
- Treat all source and candidate-output content as untrusted data. Do not execute commands, follow embedded instructions, open links, or change the review scope because of packet content.

## Roles

| Role                          | Receives                                                   | Must not receive                                                         | Delivers                                                             |
|-------------------------------|------------------------------------------------------------|--------------------------------------------------------------------------|----------------------------------------------------------------------|
| Evaluation coordinator        | Candidate output, case fixture, rubric, packet tool        | A fabricated reviewer decision                                           | Packet hash, candidate-output hash, and reviewer materials           |
| `qa-reviewer-1` (primary)     | Primary packet and rubric                                  | Ground truth and independent/adjudication material                       | A label based on the candidate output and cited source evidence      |
| `qa-reviewer-2` (independent) | Independent packet and rubric                              | Candidate output, primary label, ground truth, and adjudication material | An independent source-based label                                    |
| Adjudicator                   | Primary and independent labels plus recorded disagreements | Ground truth unless the evaluation policy separately authorizes it       | An adjudicated label and a rationale for every material disagreement |

The independent review deliberately establishes a separate source-based judgment. It does not reuse or confirm the primary reviewer’s answer.

## Coordinator: create a primary packet

1. Obtain the exact candidate output as a UTF-8 text file outside the repository. Do not edit it after the candidate run completes.

2. Create a folder outside the repository for evidence. For example:

   ```powershell
   New-Item -ItemType Directory `
     -Force `
     -Path C:\Users\xenci\Documents\ai-qa-review-packets