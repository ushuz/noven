# -*- coding:utf-8 -*-

import time
import xml.etree.cElementTree as ET

def parse(xmlstring):
    if not xmlstring:
        return
    try:
        et = ET.fromstring(xmlstring)

        to = et.find("ToUserName").text.decode("utf-8")
        fr = et.find("FromUserName").text.decode("utf-8")
        time = et.find("CreateTime").text.decode("utf-8")
        
        type = et.find("MsgType").text.decode("utf-8")
        if type == u"text":
            content = et.find("Content").text.decode("utf-8")
            
            if content == u"Hello2BizUser":
                # hello message
                # a help message should be returned at last
                return HelloMessage(to, fr, time)
            
            elif content.split()[0].lower() == u"zc":
                # sign up through weixin
                # take down uc & up for later usage
                try:
                    uc, up = content.split()[1:]
                except ValueError:
                    return
                return SignupMessage(to, fr, time, uc, up)
        
        return QueryMessage(to, fr, time)

        # id = et.find("MsgId").text.decode("utf-8")
    except Exception, e:
        # print e
        return

tpl = u'''<xml><ToUserName><![CDATA[%s]]></ToUserName>
<FromUserName><![CDATA[%s]]></FromUserName>
<CreateTime>%d</CreateTime><MsgType><![CDATA[text]]></MsgType>
<Content><![CDATA[%s]]></Content><FuncFlag>0</FuncFlag></xml>'''

def reply(received, content):
    to = received.fr
    fr = received.to
    return tpl % (to, fr, int(time.time()), content)


class WxMessage(object):
    '''Base class for weixin message.'''
    def __init__(self, to, fr, time):
        self.to = to
        self.fr = fr
        self.time = time

class HelloMessage(WxMessage):
    '''When received, a guide message should be returned to the user.'''


class QueryMessage(WxMessage):
    '''When received, [已更新] or [无更新] or [未注册] should be returned'''


class SignupMessage(WxMessage):
    def __init__(self, to, fr, time, uc, up):
        self.to = to
        self.fr = fr
        self.time = time
        self.usercode = uc
        self.password = up


if __name__ == "__main__":
    pass