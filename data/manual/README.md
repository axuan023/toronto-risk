# Manually entered data

## tts_2022_toronto_trips.csv

Source: *2022 TTS Travel Summaries by Ward for the City of Toronto* (v5.1, July 2025), Data Management Group, University of Toronto. City of Toronto pages 29–30, "New baseline" (2022n), 24-hour columns.

- `trips_to_toronto`: average weekday trips with a destination in the City of Toronto, made by residents of the whole TTS area (p. 30, total 5,671,900). **Primary table:** collisions on Toronto roads involve non-residents too.
- `trips_by_residents`: average weekday trips made by City of Toronto residents (p. 29, total 5,454,400). Used as a sensitivity check.
- `weekday_trips` = total trips × `share_pct`. The report rounds shares to whole percentages, so each count is uncertain by about ±0.5 percentage points of the total (about ±28,000 trips). GO Train in the residents table rounds to 0%.
- `median_trip_km` is the **straight-line** median distance. It is only reported for driver, passenger, transit and GO Train. Don't use it to calculate total km travelled.
- "2022n" includes trips by persons aged 5+ and all walk trips.
- Weekday averages only. Annual totals need a weekend assumption.
- `walk_cycle` combines walking and cycling. Splitting them requires a Data Retrieval System cross-tab of `mode_prime` (C = bicycle, W = walk).
