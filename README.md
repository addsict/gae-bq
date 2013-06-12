gae-bq BigQuery library for Google App Engine
------------------------------------------------
BigQuery library used in Google App Engine(GAE).  
This library uses some GAE features, such as ndb or memcache.

How to use
------------

### Single Query - BQJob
BQJob is a class to start the BigQuery job and fetch result.  
You can use either run\_sync(synchronous) or run\_async(asynchronous) method.

```python
from gae_bq import BQJob

project_id = 'example_project'
query = 'SELECT foo FROM bar'
credentials = OAUTH2_CREDENTIALS

bqjob = BQJob(project_id=project_id, 
              query=query, 
              credentials=credentials)

# run synchronously
job_result = bqjob.run_sync()

# or run asynchronously
bqjob.run_async()
# ... do other things ...
job_result = bqjob.get_result()

print job_result # [{u'foo': 10}, {u'foo': 20}, ...]
```

### Multiple Queries - BQJobGroup
BQJobGroup is a class for putting multiple BQJobs into an one group.  
Every BQJob in that group are executed concurrently.

```python
from gae_bq import BQJob, BQJobGroup

bqjob1 = BQJob(project_id=project_id, 
               query=query, 
               credentials=credentials)
bqjob2 = BQJob(project_id=project_id, 
               query=query, 
               credentials=credentials)

job_group = BQJobGroup([bqjob1, bqjob2])
# synchronously
results = job_group.run_sync()
# or asynchronously
job_group.run_async()
results = job_group.get_results()

print results # [[{'foo': 10}, {'foo': 20}], [{'bar': 'test'}]]
```

Note
-----
- Concurrent Requests to BigQUery
    - Concurrent requests to BigQuery is restricted to 20 requests by [Quota Policy](https://developers.google.com/bigquery/docs/quota-policy).
    - This library controls concurrent requests using **BQJobTokenBucket** model and default max conccurent requests is 5.
        - You can change \_MAX\_CONCURRENT\_REQUESTS variable up to 20.
    - If you want to set up concurrent requests to 20, you also have to set up at traffic controls in [api-console](https://code.google.com/apis/console/) page

License
-----------
This library is disributed as MIT license.
