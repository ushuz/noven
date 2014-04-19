# -*- coding:utf-8 -*-

import time
import xml.etree.cElementTree as ET


def parse(xmlstring):
    if not xmlstring:
        return
    try:
        et = ET.fromstring(xmlstring)

        to = et.find("ToUserName").text
        fr = et.find("FromUserName").text
        time = et.find("CreateTime").text

        type = et.find("MsgType").text

        if type == "text":
            # If Chinese characters exist, xml.etree.cElementTree will auto-
            # matically decode the contents and return unicode when invoking
            # Element.text.  So we use built-in function unicode() to cover
            # various inputs.
            content = unicode(et.find("Content").text)
            if content.startswith(" ") or content.startswith(":") or \
                content.startswith(u"："):
                return BlahMessage(to, fr, time, content)
            return QueryMessage(to, fr, time)

        if type == "event":
            # API changed since 20130326, WTF!
            # If we get a new follower, an event msg will be pushed to our
            # server of which `MsgType` is `event`.
            event = et.find("Event").text

            if event == "subscribe":
                return HelloMessage(to, fr, time)

            if event == "unsubscribe":
                return ByeMessage(to, fr, time)

            if event == "CLICK":
                key = et.find("EventKey").text
                if key == "KEY_QUERY":
                    return QueryMessage(to, fr, time)
                if key == "KEY_SIGNUP":
                    return HelloMessage(to, fr, time)
                if key == "KEY_REPORT":
                    return ReportMessage(to, fr, time)

        # `MsgId` is of no use for now.
        # id = et.find("MsgId").text.decode("utf-8")
    except Exception as e:
        print e
        return


class WxMessage(object):
    """Base class for weixin messages."""
    def __init__(self, to, fr, time):
        self.to = to
        self.fr = fr
        self.time = time


class HelloMessage(WxMessage):
    """When received, a guide message should be returned to the user."""


class ByeMessage(WxMessage):
    """When received, some cleanup work should be done."""


class QueryMessage(WxMessage):
    """When received, [已更新] or [无更新] or [未注册] should be returned."""


class BlahMessage(WxMessage):
    """Users try to contact."""
    def __init__(self, to, fr, time, content):
        super(BlahMessage, self).__init__(to, fr, time)
        self.content = content


class ReportMessage(WxMessage):
    """Users request his/her own report."""
