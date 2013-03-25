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
            # If Chinese characters exist, xml.etree.cElementTree will auto-
            # matically decode the contents and return unicode when invoking
            # Element.text.  So we use built-in function unicode() to cover
            # various inputs.
            content = unicode(et.find("Content").text)

            # Old API will be deprecated since 20130326.  As a result we have
            # to change some logics and the following way of notifying A NEW
            # FOLLOWER should be no longer valid.  But we keep it here just in
            # case and it won't cost much.
            if content == u"Hello2BizUser":
                # A new follower.
                # A guide message should be returned at last.
                return HelloMessage(to, fr, time)

            if content.split()[0].lower() == u"zc":
                # Users are signing up through weixin.  In such case, we
                # should take down `uc` & `up` for later usage.
                try:
                    uc, up = content.split()[1:]
                except ValueError:
                    return QueryMessage(to, fr, time)
                return SignupMessage(to, fr, time, uc, up)

        if type == u"event":
            # API changed since 20130326, WTF!
            # If we get a new follower, an event msg will be pushed to our
            # server of which `MsgType` is `event`.
            return HelloMessage(to, fr, time)

        return QueryMessage(to, fr, time)

        # `MsgId` is of no use at present.
        # id = et.find("MsgId").text.decode("utf-8")
    except Exception, e:
        print e
        return


tpl = u'''<xml><ToUserName><![CDATA[%s]]></ToUserName><FuncFlag>0</FuncFlag>
<FromUserName><![CDATA[%s]]></FromUserName><CreateTime>%d</CreateTime>
<MsgType><![CDATA[text]]></MsgType><Content><![CDATA[%s]]></Content></xml>'''


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
    '''When received, [已更新] or [无更新] or [未注册] should be returned.'''


class SignupMessage(WxMessage):
    def __init__(self, to, fr, time, uc, up):
        self.to = to
        self.fr = fr
        self.time = time
        self.usercode = uc
        self.password = up


if __name__ == "__main__":
    pass
