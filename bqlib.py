# -*- coding: utf-8 -*-
# Copyright 2013, Yuuki Furuyama
# Released under the MIT License.

""" bqlib - BigQuery python library """

import logging
import urllib2
import time
import sys
import datetime
import os
import re

from bigquery_client import BigqueryError, BigqueryNotFoundError, BigqueryClient


_API = 'bigquery'
_API_VERSION = 'v2'
_DISCOVERY_URI = ('https://www.googleapis.com/discovery/v1/apis/'
                  '{api}/{apiVersion}/rest')

class BQError(Exception):
    def __init__(self, message, error):
        self.message = message
        self.error = error


class BQJob(object):
    """BigQuery Job model

    You can use this model to run BigQuery job.
    """
    def __init__(self, discovery_document_storage=None, 
                 verbose=True, **kwargs):
        super(BQJob, self).__init__()

        self.verbose = verbose

        for key, value in kwargs.items():
            setattr(self, key, value)
        for required_flag in ('http', 'project_id'):
            if not kwargs.has_key(required_flag):
                raise ValueError('Missing required flag: %s' % (required_flag,))
        default_flags = {
            'job_reference': None,
        }
        for key, value in default_flags.iteritems():
            if not hasattr(self, key):
                setattr(self, key, value)

        if not hasattr(self, 'bq_client'):
            if discovery_document_storage is None and BQHelper.is_gae_runtime():
                from google.appengine.api import memcache
                discovery_document_storage = memcache

            discovery_document = BQHelper.retrieve_discovery_document(
                    discovery_document_storage)
            bq_client = BigqueryClient(
                    api=_API,
                    api_version=_API_VERSION,
                    project_id=self.project_id,
                    discovery_document=discovery_document,
                    wait_printer_factory=BigqueryClient.QuietWaitPrinter
                    )

            # BigqueryClient requires 'credentials' to build 
            # apiclient instance. But using 'authorized http' 
            # is more versatile than using 'credentials'.
            bq_client._apiclient = BQHelper.build_apiclient(
                discovery_document,
                self.http)
            self.bq_client = bq_client

    def run_sync(self, timeout=sys.maxint):
        self.run_async()
        try:
            return self.get_result(timeout=timeout)
        except StopIteration as e:
            raise BQError(message='timeout', error=[])

    def run_async(self, **kwargs):
        # BQJobTokenBucket.pull_token()
        try:
            job = run_func_with_backoff(self.bq_client.Query, query=self.query, sync=False)
        except BigqueryError as err:
            message = None
            error = None
            if hasattr(err, 'message'):
                message = err.message
            if hasattr(err, 'error'):
                error = err.error
            raise BQError(message=message, error=error)
        self.job_reference = self.bq_client.ConstructObjectReference(job)

    def get_result(self, timeout=sys.maxint):
        """ get response from BigQuery

        same signature with async urlfetch : rpc.get_result()
        """
        bq_client = self.bq_client
        job_reference = self.job_reference
        job = bq_client.WaitJob(job_reference,
                wait=timeout,
                wait_printer_factory=bq_client.wait_printer_factory)
        if self.verbose:
            self._print_verbose(job)
        schema, rows = bq_client.ReadSchemaAndRows(
                job['configuration']['query']['destinationTable'],
                max_rows=(2**31-1) # max_rows must be under uint32
                )
        results = []
        for row in rows:
            result = {}
            for (field, value) in zip(schema, row):
                converted_value = BQHelper.convert_type(field['type'], value)
                result[field['name']] = converted_value
            results.append(result)
        return results

    def _print_verbose(self, job_dict):
        log_format = """
        ############### Bigquery Query Results ###############
         projectId           : {project_id}
         jobId               : {job_id}
         query               : {query}
         totalBytesProcessed : {total_bytes_processed} Bytes
         cacheHit            : {cache_hit}
        ######################################################
        """
        logging.info(log_format.format(
            project_id=job_dict['jobReference']['projectId'],
            job_id=job_dict['jobReference']['projectId'],
            query=job_dict['configuration']['query']['query'],
            total_bytes_processed=job_dict['statistics']['query']['totalBytesProcessed'],
            cache_hit=job_dict['statistics']['query'].get('cacheHit'))
        )


class BQJobGroup(object):
    """Group for BigQuery job

    You can use this model to put multiple BQJob
    into an one group.
    'run_sync' and 'ryn_async' method are executed concurrently.
    """
    def __init__(self, jobs=[]):
        self.jobs = jobs

    def add(self, bqjob):
        self.jobs.append(bqjob)

    def remove(self, bqjob):
        # TODO
        pass

    def get_jobs(self):
        return self.jobs

    def run_sync(self, timeout=sys.maxint):
        # start job
        self.run_async()

        # get job result
        results = []
        for job in self.jobs:
            results.append(job.get_result(timeout=timeout))
        return results

    def run_async(self):
        for job in self.jobs:
            job.run_async()

    def get_results(self):
        results = []
        for job in self.jobs:
            results.append(job.get_result())
        return results


class BQHelper(object):
    """Static helper methods and classes not provided by bigquery library."""
    def __init__(self, *unused_args, **unused_kwargs):
        raise NotImplementedError('cannot instantiate this static class')

    @staticmethod
    def is_gae_runtime():
        server_software = os.environ.get('SERVER_SOFTWARE')
        if server_software is not None:
            num = r'\d+'
            gae = r'Google App Engine/%s\.%s\.%s' % (num, num, num)
            gae_dev = r'Development/%s\.%s' % (num, num)
            return bool(re.match(gae, server_software) or 
                        re.match(gae_dev, server_software))
        else:
            return False

    @staticmethod
    def retrieve_discovery_document(storage=None):
        u""" Retrieve discovery document for BigQuery
        
        At first, discovery document is to be fetched from memcache.
        If discovery document doesn't exist in memcache,
        publish HTTP request to get a document discovery and set it to memcache
        """
        if storage is not None and hasattr(storage, 'get'):
            document_key = 'discovery_document'
            discovery_document = storage.get(document_key)
            if discovery_document is not None:
                return discovery_document

        params = {'api': _API, 'apiVersion': _API_VERSION}
        request_url = _DISCOVERY_URI.format(**params)
        logging.info('fetch discovery document from %s' % request_url)

        try:
            response = urllib2.urlopen(request_url)
            body = response.read()
        except urllib2.HTTPError as err:
            raise err

        if storage is not None and hasattr(storage, 'set'):
            storage.set(document_key, body, time=86400) # 86400 = 1 day

        return body

    @staticmethod
    def build_apiclient(discovery_document, http):
        from apiclient import discovery
        from bigquery_client import BigqueryModel, BigqueryHttp

        bigquery_model = BigqueryModel()
        return discovery.build_from_document(
            discovery_document, http=http,
            model=bigquery_model,
            requestBuilder=BigqueryHttp.Factory(bigquery_model))


    @staticmethod
    def convert_type(field_type, value):
        """convert type of 'value' to 'field_type'

        filedtype: STRING, INTEGER, FLOAT, BOOLEAN, TIMESTAMP
        TODO:
            required to implement Nested and Repeated Data type
            https://developers.google.com/bigquery/docs/data
        """
        if field_type is None or value is None:
            return None

        if not is_str_or_unicode(field_type) or not is_str_or_unicode(value):
            raise TypeError('field_type and value must be unicode or str type')

        field_type = field_type.upper()
        supported_field_type = (
                'STRING',
                'INTEGER',
                'FLOAT',
                'BOOLEAN',
                'TIMESTAMP',
                )
        if not field_type in supported_field_type:
            raise ValueError

        if field_type == 'STRING':
            return str(value)
        elif field_type == 'INTEGER':
            return int(value)
        elif field_type == 'FLOAT':
            return float(value)
        elif field_type == 'BOOLEAN':
            if value == 'True':
                return True
            else:
                return False
        elif field_type == 'TIMESTAMP':
            return datetime.datetime.utcfromtimestamp(float(value))

    @staticmethod
    def build_fully_qualified_table_name(project_id, dataset_id, table_id):
        """Build fully qualified table name from project-id, dataset-id, and table-id"""
        return "[%s:%s.%s]" % (project_id, dataset_id, table_id)



"""utility functions"""
def is_str_or_unicode(obj):
    return isinstance(obj, unicode) or isinstance(obj, str)


def run_func_with_backoff(func, retry=3, backoff=1, **kwargs):
    count = 0
    while count < retry:
        try:
            return func(**kwargs)
        except BigqueryNotFoundError as err:
            raise err
        except BigqueryError as err:
            logging.info(err.message)
            logging.info('will retry after %d seconds' % backoff)
            time.sleep(backoff)
            count += 1
            backoff *= 2
    raise BQError(message='%d times retried but failed' % retry, error=None)