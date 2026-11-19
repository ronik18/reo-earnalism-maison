import json
from unittest.mock import Mock,patch
from django.test import SimpleTestCase,override_settings
from core.api import DomainError
from .providers import purge_catalog_cache

@override_settings(CLOUDFLARE_ZONE_ID='a'*32,CLOUDFLARE_CACHE_PURGE_TOKEN='unit-test-secret',PUBLIC_BASE_URL='https://maison.example',MAISON_PUBLICATION_TERRITORIES=['IN','US'])
class CatalogPurgeProviderTests(SimpleTestCase):
    def urls(self):return {'urls':['https://maison.example/api/v1/home?locale=en&territory=IN']}
    def connection(self,status=200,body=None):
        connection=Mock();response=Mock(status=status)
        response.read.side_effect=[json.dumps(body if body is not None else {'success':True,'errors':[]}).encode(),b'']
        connection.getresponse.return_value=response
        return connection

    def test_fixed_host_exact_urls_no_global_purge_and_ack_is_not_readback(self):
        connection=self.connection()
        with patch('operations.providers.http.client.HTTPSConnection',return_value=connection) as factory:
            result=purge_catalog_cache(self.urls())
        self.assertEqual(factory.call_args.args[0],'api.cloudflare.com');self.assertEqual(factory.call_args.kwargs['timeout'],3)
        request=connection.request.call_args
        self.assertEqual(request.args,('POST','/client/v4/zones/'+'a'*32+'/purge_cache'))
        self.assertEqual(json.loads(request.kwargs['body']),{'files':self.urls()['urls']})
        self.assertEqual(result['status'],'acknowledged');self.assertFalse(result['readback_verified'])
        self.assertNotIn('secret',str(result));connection.close.assert_called_once()

    def test_all_language_and_explicit_content_variants_keep_exact_purge_scope(self):
        from operations.providers import _urls
        urls=['https://maison.example/api/v1/catalog?territory=IN','https://maison.example/api/v1/catalog?locale=all&territory=IN','https://maison.example/api/v1/catalog?locale=bn&territory=IN']
        self.assertEqual(_urls({'urls':urls},'maison.example'),urls)

    def test_missing_emitted_urls_fails_closed_before_network(self):
        with patch('operations.providers.http.client.HTTPSConnection') as factory:
            with self.assertRaises(DomainError) as error:purge_catalog_cache({'edition_id':'unused'})
            self.assertEqual(error.exception.code,'catalog_purge_urls_missing');factory.assert_not_called()

    @override_settings(CLOUDFLARE_CACHE_PURGE_TOKEN='')
    def test_unconfigured_provider_never_claims_success(self):
        with self.assertRaises(DomainError) as error:purge_catalog_cache(self.urls())
        self.assertEqual(error.exception.code,'provider_not_enabled')

    def test_rejects_external_private_filtered_noncanonical_and_oversized_batches(self):
        bad=['https://other.example/api/v1/home?locale=en&territory=IN',
            'https://maison.example/api/v1/me/profile',
            'https://maison.example/api/v1/catalog?locale=en&territory=IN&q=test',
            'https://maison.example/api/v1/home?territory=IN&locale=en',
            'https://maison.example/api/v1/home?locale=en&territory=CN',
            'https://maison.example/api/v1/home?locale=en&locale=bn',
            'https://maison.example/api/v1/home']
        with patch('operations.providers.http.client.HTTPSConnection') as factory:
            for url in bad:
                with self.subTest(url=url),self.assertRaises(DomainError):purge_catalog_cache({'urls':[url]})
            with self.assertRaises(DomainError):purge_catalog_cache({'urls':self.urls()['urls']*31})
            factory.assert_not_called()

    def test_rate_limit_http_failure_and_false_success_are_retryable_failures(self):
        for status,body in [(429,None),(503,None),(200,{'success':False,'errors':[]})]:
            with self.subTest(status=status,body=body),patch('operations.providers.http.client.HTTPSConnection',return_value=self.connection(status,body)):
                with self.assertRaises(DomainError) as error:purge_catalog_cache(self.urls())
                self.assertEqual(error.exception.status,503)

    def test_timeout_and_response_size_are_bounded(self):
        connection=self.connection();connection.getresponse.side_effect=TimeoutError()
        with patch('operations.providers.http.client.HTTPSConnection',return_value=connection):
            with self.assertRaises(DomainError) as error:purge_catalog_cache(self.urls())
            self.assertEqual(error.exception.code,'provider_outcome_unknown')
        connection=self.connection();connection.getresponse.return_value.read.side_effect=[b'x'*65537]
        with patch('operations.providers.http.client.HTTPSConnection',return_value=connection):
            with self.assertRaises(DomainError):purge_catalog_cache(self.urls())
