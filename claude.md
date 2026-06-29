This is a python application that is designed to run directly from github through a daily or weekly action. The information provided by the user for now will be hard coded in the profile.yaml file.

Its  goal is to provide a regular email to a user with a list of potential job opportunities. This will filter out jobs based upon location, salary range, employment type (permanent, contract, part time), and job suitability. This application also has the important role of only returning jobs from companies and organisations that are part of the uk governments list of approved sponsor companies for immigrants. There is a list of these companies held in a csv file located in:
/assets/sponsor_cache.csv
