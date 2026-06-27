Job Search APIs
1. LinkedIn + Indeed — via python-jobspy
File: searchers/jobspy_searcher.py

This is a third-party Python library that wraps both platforms. What we pass to it:

Parameter	Current Value	What It Does
site_name	["linkedin", "indeed"]	Which platforms to hit
search_term	query string	Free-text keyword search
location	Bristol	Location string
distance	50 (miles)	Radius from location
results_wanted	50	Max results per query
country_indeed	"UK"	Country for Indeed (LinkedIn infers from location)
What jobspy can also accept (not currently used):

job_type — "fulltime", "parttime", "contract", "internship"
is_remote — True/False
hours_old — only return jobs posted within N hours
easy_apply — LinkedIn Easy Apply only
Salary filtering happens client-side after fetch: we parse min_amount from the structured fields, then fall back to a regex scan of the description text (£60,000 / £60k style).

2. Reed API
File: searchers/reed.py

A proper REST API (reed.co.uk/api/1.0/search). Salary filtering is server-side here.

Parameter	Current Value	What It Does
keywords	query string	Free-text keyword search
locationName	Bristol	Location string
distancefromLocation	50	Radius in miles
minimumSalary	60000	Server-side salary floor
resultsToTake	100	Max results per query
Reed also supports (not currently used):

maximumSalary — salary ceiling
fullTime / partTime / contract / permanent — boolean employment type filters
postedByRecruitmentAgency / postedByDirectEmployer — source filters
graduate — graduate roles only
3. NHS Jobs — Web Scraper
File: searchers/nhs_jobs.py

Not an official API — it scrapes the search results page at jobs.nhs.uk/candidate/search/results. There's no authentication; it mimics a browser request.

Parameter	Current Value	What It Does
keyword	query string	Free-text keyword search
location	Bristol	Location string
distance	50	Radius in miles
language	"en"	Language filter
Salary filtering happens client-side by parsing the first £ figure from the salary text on each result card.

Limitation: No job description is fetched from NHS Jobs — the description field is always returned as an empty string. This means the AI scorer only sees the title, company, location, and salary for NHS jobs.

Key Gap to Note
All three sources accept the same three core inputs from our side: query, location, distance. The agentic loop varies the query string per round — that's the only lever currently being pulled. Employment type, remote-only, posting date, and contract type are all available in jobspy and Reed but unused.