# REFIT House 1 cross-house co-activity recheck

Date: 2026-09-29. Status: **independent second-household power-trace recheck completed; machine-screened, not independently human-reviewed.**

## Purpose and source identity

House 1 is used as a second household to check whether the observed pairwise appliance-power overlap found in the House 5 trace is unique to that one home. It is not being used to infer user requests, task deadlines, device controllability, or electrical-circuit conflicts.

The source is the publisher-cleaned `CLEAN_House1.csv` from REFIT's Zenodo record (DOI `10.5281/zenodo.5063428`, CC BY 4.0). The local file is 400,840,083 bytes; its MD5 is `f5336d80c700f866af0d997ea8d39146` and SHA-256 is `15b8c60c0bf32f1fccfafae81a9bb04e1a24937cfb29840d5b955310df25ff30`. The published ReadMe maps `Appliance4` to the tumble dryer, `Appliance5` to the washing machine, and `Appliance6` to the dishwasher.

Full-file audit: 6,960,008 rows; 58,183 `Issues=1` rows (0.84%); no missing or nonnumeric values in the three target channels; 12,778 gaps longer than 16 seconds, with the largest gap about 41.6 days. The flagged rows are excluded and break candidate windows. Long gaps also break windows. These quality rules follow the publisher's flag and the declared 8-second nominal cadence.

## Screening method

For each device pair, a sample qualifies when both mapped channels meet the selected power threshold, `Issues=0`, and adjacent timestamps differ by no more than 16 seconds. A contiguous run is summarized as last timestamp minus first timestamp plus 8 seconds. Thresholds of 50, 100, and 300 W are sensitivity checks, not physical definitions of a task or conflict. The date range is 2013-10-09 inclusive to 2015-07-11 exclusive.

| Threshold | Washer + dishwasher | Dryer + washer | Dryer + dishwasher |
|---|---:|---:|---:|
| 50 W | 52 windows; 2 at least 300 s | 23; 1 at least 300 s | 0 |
| 100 W | 41 windows; 2 at least 300 s | 19; 1 at least 300 s | 0 |
| 300 W | 9 windows; 2 at least 300 s | 4; 0 at least 300 s | 0 |

One washer–dishwasher co-activity interval persists across thresholds:

| Threshold | Measured interval | Estimated duration | Boundary review |
|---|---|---:|---|
| 50 W | 2014-12-27 11:55:27–12:03:29 | 490 s | Exploratory sensitivity interval |
| 100 W | 2014-12-27 11:56:07–12:03:22 | 443 s | Both adjacent boundaries are quality-clear and below the pair threshold |
| 300 W | 2014-12-27 11:58:07–12:03:22 | 323 s | Both adjacent boundaries are quality-clear and below the pair threshold |

The 100 W run has 66 qualifying rows; the 300 W run has 48. The independent context exports verified that every candidate row meets its threshold, has `Issues=0`, and respects the selected maximum gap. The review-status fields remain blank because no second human reviewer has inspected them.

## Three-channel check

The 100 W extraction produced 60 pair windows in total (19 dryer–washer, 41 washer–dishwasher, and no dryer–dishwasher windows). The 3,975-row context export was searched for same-row activity of all three mapped channels at or above 100 W, excluding `Issues=1` and breaking bouts at gaps over 16 seconds. It found **zero qualifying source rows and zero bouts**. Any clear sample with all three channels at or above 100 W would necessarily belong to at least one of these qualifying pair windows, so this is a full-coverage negative result for the selected 100 W rule over the audited date range, subject to REFIT's cleaning and sensor limitations. It says nothing about lower thresholds or unflagged underlying physical activity.

This means House 1 supplies a useful second-home two-device case, but not a three-channel-at-100-W trace for a three-Agent load case. House 5's single longer three-channel segment remains quality-boundary-uncertain. A third-home search is therefore justified only to find and verify a distinct multi-load case, rather than to collect another copy of pairwise overlap.

## What this supports

This recheck supports a narrow claim: a multi-minute, two-channel power co-activity trace can be found in a second REFIT household, and the selected example survives a 50/100/300 W threshold sweep. It makes House 1 a candidate source for empirical device-load replay and parameter sensitivity checks.

It does **not** show that two users issued tasks at the same time, that the appliances were in complete operating cycles, that a shared household circuit exceeded capacity, or that an Agent could control either device. It also does not establish how common the overlap is across households. REFIT's nominal 8-second, asynchronous, cleaned readings are too coarse to validate sub-second actions or exact physical event boundaries.

For HomeCoord-Bench, the trace may parameterize the observed power/background-load portion of a controlled replay. Task arrivals, deadlines, action permissions, and any capacity budget must remain explicitly researcher-defined variables. The paper should call this a **trace-backed controlled replay**, not a real household multi-Agent execution trace. A third household is useful only if it is being used to test a distinct claim—especially three-channel overlap or robustness across homes—not simply to increase the number of similar examples.

## Reproducibility artifacts

- Full source audit: [`refit_house1_source_audit_20260929.json`](../homecoord_bench/results/refit_house1_source_audit_20260929.json)
- 50 W, 100 W, and 300 W window summaries: [`refit_house1_coactivity_50W_20260929.json`](../homecoord_bench/results/refit_house1_coactivity_50W_20260929.json), [`refit_house1_coactivity_windows_all_20260929.json`](../homecoord_bench/results/refit_house1_coactivity_windows_all_20260929.json), and [`refit_house1_coactivity_300W_20260929.json`](../homecoord_bench/results/refit_house1_coactivity_300W_20260929.json)
- 100 W review set and context: [`refit_house1_coactivity_review_summary_20260929.csv`](../homecoord_bench/results/refit_house1_coactivity_review_summary_20260929.csv) and [`refit_house1_coactivity_review_rows_20260929.csv`](../homecoord_bench/results/refit_house1_coactivity_review_rows_20260929.csv)
- 300 W review set and context: [`refit_house1_coactivity_300W_review_summary_20260929.csv`](../homecoord_bench/results/refit_house1_coactivity_300W_review_summary_20260929.csv) and [`refit_house1_coactivity_300W_review_rows_20260929.csv`](../homecoord_bench/results/refit_house1_coactivity_300W_review_rows_20260929.csv)
- All 100 W pair-window contexts and three-channel scan: [`refit_house1_all_coactivity_100W_review_rows_20260929.csv`](../homecoord_bench/results/refit_house1_all_coactivity_100W_review_rows_20260929.csv), [`refit_house1_triple_coactivity_bouts_20260929.json`](../homecoord_bench/results/refit_house1_triple_coactivity_bouts_20260929.json), and [`refit_house1_triple_coactivity_bouts_20260929.csv`](../homecoord_bench/results/refit_house1_triple_coactivity_bouts_20260929.csv)
- Extractor now accepts `--house-id H1`; this avoids incorrectly labeling House 1 results with the former hard-coded House 5 prefix.

Example command:

```powershell
python homecoord_bench/extract_refit_coactivity_windows.py `
  homecoord_bench/data/external/REFIT/CLEAN_House1.csv `
  homecoord_bench/results/refit_house1_coactivity_windows_all_20260929.json `
  --start-date 2013-10-09 `
  --end-date-exclusive 2015-07-11 `
  --threshold-w 100 `
  --max-gap-seconds 16 `
  --dryer-column Appliance4 `
  --washer-column Appliance5 `
  --dishwasher-column Appliance6 `
  --house-id H1
```

## Source

- Murray, D., Stankovic, L., & Stankovic, V. (2017). *An electrical load measurements dataset of United Kingdom households from a two-year longitudinal study*. Scientific Data 4, 160122. [Paper](https://www.nature.com/articles/sdata2016122), [per-house appliance table](https://www.nature.com/articles/sdata2016122/tables/4).
- University of Strathclyde, [official cleaned REFIT dataset page](https://pureportal.strath.ac.uk/en/datasets/refit-electrical-load-measurements-cleaned/) and [cleaned-data ReadMe](https://pureportal.strath.ac.uk/ws/portalfiles/portal/52873458/REFIT_Readme.txt).
- Murray & Stankovic, [REFIT cleaned data, Zenodo DOI 10.5281/zenodo.5063428](https://zenodo.org/records/5063428).
