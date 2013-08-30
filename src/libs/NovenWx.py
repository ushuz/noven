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

            if content == u"菜单":
                # Requesting menu.
                return MenuMessage(to, fr, time)

            if content.startswith(u":") or content.startswith(u"："):
                # Users try to contact.
                return BlahMessage(to, fr, time, content)

        if type == u"event":
            # API changed since 20130326, WTF!
            # If we get a new follower, an event msg will be pushed to our
            # server of which `MsgType` is `event`.
            event = et.find("Event").text.decode("utf-8")

            if event == u"subscribe":
                return HelloMessage(to, fr, time)
            elif event == u"unsubscribe":
                return ByeMessage(to, fr, time)

        return QueryMessage(to, fr, time)

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


class MenuMessage(WxMessage):
    """When received, menu should be returned."""


class BlahMessage(WxMessage):
    """Users try to contact."""
    def __init__(self, to, fr, time, content):
        self.to = to
        self.fr = fr
        self.time = time
        self.content = content


if __name__ == "__main__":
    pass
