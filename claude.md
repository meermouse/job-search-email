This is a python application that is designed to run directly from github through a daily or weekly action. The information provided by the user for now will be hard coded in the profile.yaml file.

Its eventual goal is to provide a regular email to a user with a list of potential job opportunities. This will filter out jobs based upon location, salary range, employment type (permanent, contract, part time), and job suitability. This application also has the important role of only returning jobs from companies and organisations that are part of the uk governments list of approved sponsor companies for immigrants. There is a list of these companies held in a csv file located in:
/assets/sponsor_cache.csv


This is an application in progress, i am currently going down the list and implementing each task one by one.
Current tasks completed: 1,2,3

# Job Search Email Filter Step Layout

This document describes the initial plan generation flow and the file locations for each filter step.

## 1. Profile loading
- File: `src/job_search_email/main.py`
- Function: `load_profile`
- Purpose: Read `profile.yaml` and deserialize the profile into a `Profile` object.

## 2. Query generation
- File: `src/job_search_email/queries.py`
- Function: `generate_queries`
- Purpose: Create 8 tailored search queries using the profile's target roles and skills.

## 3. Clinical and employment exclusions
- File: `src/job_search_email/exclusions.py`
- Function: `get_exclusions`
- Purpose: Return exclusion keyword groups for clinical roles and non-permanent employment types.

## 4. NHS band rules
- File: `src/job_search_email/nhs_rules.py`
- Function: `get_nhs_rules`
- Purpose: Return default NHS band floor rules and the London remote exception.

## 5. Evaluator notes
- File: `src/job_search_email/evaluator_notes.py`
- Function: `get_evaluator_notes`
- Purpose: Provide notes to support scoring of candidate opportunities.

## 6. Plan assembly
- File: `src/job_search_email/main.py`
- Function: `generate_search_plan`
- Purpose: Compose the final `SearchPlan` object from the profile fingerprint and all filter outputs.

## 7. Caching and persistence
- File: `src/job_search_email/main.py`
- Functions: `load_cached_plan`, `save_cached_plan`, `write_search_plan`
- Purpose: Cache generated plans in `search_plan_cache.json` and write the active plan to `search_plan.json`.
