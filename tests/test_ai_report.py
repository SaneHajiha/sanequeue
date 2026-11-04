import json
import unittest
from sanequeue.reporting.ai_report import parse,AIReportUnavailable


class Response:
    status=200
    def __init__(self,text):self.text=text
    def getheader(self,name,default=None):return default
    def read(self,n):return json.dumps({'status':'completed','output':[{'type':'message',
        'content':[{'type':'output_text','text':self.text}]}]}).encode()


class Connection:
    last=None
    def __init__(self,host,timeout):
        assert host=='api.openai.com' and timeout==12
        Connection.last=self
    def request(self,method,path,body,headers):self.method=method;self.path=path;self.body=body;self.headers=headers
    def getresponse(self):return Response('{"metric":"count","direction":"inbound"}')
    def close(self):pass


class AIReportTests(unittest.TestCase):
    def test_opt_in_structured_intent_and_number_redaction(self):
        env={'SANEQUEUE_AI_REPORT_ALLOW_EXTERNAL':'1','SANEQUEUE_AI_REPORT_OPENAI_KEY':'sk-1234567890123456',
             'SANEQUEUE_AI_REPORT_MODEL':'configured-model'}
        self.assertEqual(parse('تعداد تماس ورودی شماره ۰۹۱۲۳۴۵۶۷۸۹',environ=env,connection_factory=Connection),
                         {'metric':'count','direction':'inbound'})
        payload=json.loads(Connection.last.body)
        self.assertNotIn('۰۹۱۲۳۴۵۶۷۸۹',str(payload));self.assertFalse(payload['store'])
        self.assertEqual(Connection.last.path,'/v1/responses')
        self.assertNotIn('tools',payload)
        with self.assertRaises(AIReportUnavailable):parse('hello',environ={},connection_factory=Connection)

    def test_rejects_unexpected_model_output(self):
        class Bad(Connection):
            def getresponse(self):return Response('{"metric":"count","direction":"all","sql":"select *"}')
        env={'SANEQUEUE_AI_REPORT_ALLOW_EXTERNAL':'1','SANEQUEUE_AI_REPORT_OPENAI_KEY':'sk-1234567890123456',
             'SANEQUEUE_AI_REPORT_MODEL':'configured-model'}
        with self.assertRaises(AIReportUnavailable):parse('test',environ=env,connection_factory=Bad)

    def test_comparison_is_a_whitelisted_intent_without_model_tools(self):
        class Comparison(Connection):
            def getresponse(self):return Response('{"metric":"compare_answer_rate","direction":"all"}')
        env={'SANEQUEUE_AI_REPORT_ALLOW_EXTERNAL':'1','SANEQUEUE_AI_REPORT_OPENAI_KEY':'sk-1234567890123456',
             'SANEQUEUE_AI_REPORT_MODEL':'configured-model'}
        self.assertEqual(parse('نرخ پاسخ را با دوره قبل مقایسه کن',environ=env,connection_factory=Comparison),
                         {'metric':'compare_answer_rate','direction':'all'})
        self.assertNotIn('tools',json.loads(Connection.last.body))
