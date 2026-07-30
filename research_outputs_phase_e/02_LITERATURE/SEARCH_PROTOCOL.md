# Auditable search protocol

Search date was frozen at 2026-07-31.  The Phase-D DOI/official-source corpus was retained and extended using Crossref DOI metadata plus primary IEEE, Elsevier, Wiley, IET, EAI, journal, NERC, and official preprint records.  Search families were preregistered as: (1) black-box/multimode IBR modeling; (2) data-driven or black-box frequency control; (3) set-membership/adaptive/tube MPC; (4) active/dual control and safe identification; and (5) multi-area AGC/ACE with constrained resources.

Inclusion required relevance to at least one family and exact title/year/venue metadata from a DOI registry or primary publisher.  Preprints are explicitly non-formal neighboring work.  Duplicate DOIs and normalized titles are rejected.  Theme labels are non-exclusive because one paper can legitimately connect, for example, data-driven frequency control and multi-area ACE.  Theme counts therefore measure coverage, not the number of mutually exclusive records.

No search-result snippet was treated as a literature record.  Crossref responses for every new indexed DOI are frozen in `CROSSREF_SNAPSHOT.json`; the one non-Crossref DOI is separately marked as publisher-page verified.
