# Literature Search and Verification Log

## Date and scope

- Search/verification date: 2026-07-30.
- Sources prioritized: IEEE primary publication metadata, Crossref exact DOI registry, publisher records, NERC official reports, IEEE Standards Association, and arXiv only for declared frontier supplementation.
- Topics: black-box/switching IBR identification; data-driven/Koopman/DeePC control; robust set-adaptive MPC; safe dual/active identification; multi-area AGC/ACE; IBR frequency control; RMS/DAE/EMT validation and industry model-quality evidence.

## Query families

- Exact title/document search for IEEE document 11313680 and its Crossref DOI.
- `black-box inverter dynamic identification multiple modes`.
- `inverter-based resources fast frequency control multi-area ACE tie-line`.
- `data-enabled predictive control grid-connected power converter`.
- `robust adaptive model predictive control set membership`.
- `dual model predictive control active learning safe exploration`.
- `multi-area model predictive load frequency control battery`.
- `ANDES Python cyber-physical power system simulation`.
- NERC official searches for model-quality deficiencies, IBR performance, Odessa 2022 and EMT operations planning.

## Automated integrity rules

`scripts/phase_c/c1_verify_literature.py` resolves each DOI through Crossref, requires an exact normalized title-fragment match, extracts the registered year/authors/venue, and rejects mismatches. Official/preprint URLs must return a verified HTTPS status. The run produced:

- 50 total records;
- 45 formal peer-reviewed/standard records;
- 27 records after 2021;
- 45 exact DOI/title/year checks;
- five official/preprint HTTPS checks returning 200;
- zero fabricated entries.

Two initially miscited DOI values were rejected and corrected in `progress/REPAIR_LEDGER.md`. A Conda CA-chain problem was repaired using the maintained CA bundle without disabling TLS validation.

## Search limitations

- Subscription walls limited full-text inspection for some IEEE/Elsevier/Wiley records; claims were therefore kept at the abstract/metadata level unless an accepted manuscript or open source was available.
- The 2026 Koopman-frequency item remains explicitly a preprint and is not counted as formal evidence.
- Absence from this matrix is not proof no adjacent work exists; the novelty claim is narrowly stated as the verified intersection, not universal priority.
