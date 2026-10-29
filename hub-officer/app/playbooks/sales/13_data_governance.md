# Block 1 · Data governance: clean CRM, pipeline, forecast and conversion rates

Bad data produces confident wrong decisions. A senior seller treats the CRM as a product.

## Clean CRM rules
- **One record per company, keyed by domain** (and by Google Maps place_id when it came from Maps). Never create duplicates; update the existing record.
- **Every record has:**
  - source: maps, search, inbound or referral;
  - segment and city;
  - status;
  - number of touches;
  - last contact date;
  - the next action.
- **Write notes in facts, not feelings:** "asked about price of the Pro plan; uses spreadsheet for glosas", not "very interested!!".
- Opt-outs and "no" answers are recorded and suppressed forever. Never re-import them.

## Pipeline management
- An opportunity without a next action and a date is not in the pipeline; it is a wish. Close it or schedule it.
- **Aging:** if an opportunity has stayed in a stage for more than twice the average time, flag it as at risk.

## Conversion rates
Compute stage-to-stage rates: contacted→engaged, engaged→qualified, qualified→trial, trial→paid.
- Always report the **sample size** next to a rate. Below 30 records a rate is a hint, not a fact.
- Compare by segment, city, message variant and source to find where to invest.

## Forecast
- **Weighted pipeline** = Σ (opportunity value × stage probability). Use observed stage probabilities once you have enough data; until then use conservative defaults and say so.
- **Commit:** only deals with a confirmed next step and date this period.
- Present a range (conservative / likely), never a single heroic number. Track forecast vs. actual every month to calibrate.
