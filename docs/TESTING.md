# Test Plan, Sample Data and Expected Results

Run all tests: `python -m unittest discover -v` (24 tests, about 5 seconds, uses a temporary database).

## Sample data

| | Lost report | Found report | Unrelated found report |
|---|---|---|---|
| Item | Black Samsung phone | Samsung mobile | Red umbrella |
| Category / colour / brand | Phone / black / Samsung | Phone / black / Samsung | Others / red / - |
| Description | Black Samsung mobile with a cracked screen and blue case | Found a black Samsung phone with cracked screen near the library | Large red folding umbrella left in the canteen |
| Place / date | Central library, 2026-11-20 | Library entrance, 2026-11-21 | Canteen |
| Private clue | - | lock screen photo of a golden retriever dog | - |

## Scenarios

| # | Scenario | Test | Expected result |
|---|---|---|---|
| 1 | Register and login | `test_01_register_and_login` | Valid signup redirects; duplicate email, weak password, wrong password rejected; login reaches dashboard; logout blocks dashboard |
| 2 | Lost report | `test_02_03_report_lost_and_found` | Saved (stats lost=1); description "x" rejected with 400 |
| 3 | Found report | same | Saved (stats found=1) |
| 4 | Image upload | `test_04_image_upload_validation` | PNG stored; `.exe`, text renamed `.jpg`, and `../../evil.png` rejected; nothing extra stored |
| 5 | Text matching | `test_similar_items_score_high` / `test_different_items_score_low` | Phone pair: text > 0.5, combined >= 0.7. Phone vs umbrella: combined < 0.4 |
| 6 | Image matching | `TestImageMatching` | Same image ~1.0; noisy copy > 0.7; different image < 0.5; missing image returns None |
| 7 | Combined score | `test_combined_formula`, `test_05_to_08...` | `0.45*text + 0.25*meta + 0.30*image` (no image: `0.60*text + 0.40*meta`) |
| 8 | Real-time notifications | `test_05_to_08_matching_and_realtime` | `new_notification` pushed to rooms of both users, plus `stats_update` and `new_report`; unread badge 1 then 0 after reading |
| 9 | Claim submission | `test_09_to_12...` | Only the owner can open the claim form; claim saved as **pending** (never auto-approved); second claim refused |
| 10 | Admin approval | same | Status becomes approved; admin-only route |
| 11 | Return update | same | Both items `returned`, stats returned=1, potential=0, contacts released to both users |
| 12 | Unauthorised access | `test_12_unauthorized_access` | Anonymous users redirected; normal user gets 403 on `/admin` and admin actions; `/api/stats` gives 401 |

Extra checks: self-matching is prevented, password stored hashed, missing CSRF token gets 400, rejection reopens the match,
admin removal cascades to matches, finder never sees the claimant's answers or the AI score.

## Manual real-time check (cannot be automated here)

Open two different browsers, follow README section 2, and confirm the toast and bell badge appear in both within a second
without a page refresh. (Automated tests verify that the server pushes the events to the correct rooms.)
