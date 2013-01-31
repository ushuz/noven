# -*- coding:utf-8 -*-

import json
import requests


class AuthError(Exception):
    '''Wrong mobileno or password, or not logged in.'''


class ConnError(Exception):
    '''Failed to connect to fetion servers.'''


class Fetion(object):
    '''A simplified 3G Fetion.
    Only reserved login(), send_sms(), logout().'''
    host = "http://f.10086.cn"

    def __init__(self, mobile, password):
        self.mobile, self.password = mobile, password
        self.session = requests.session()

    def login(self):
        '''/im5/login/loginHtml5.action
        :m
        :pass
        :captchaCode    :None
        :checkCodeKey   :null'''
        login_payload = {
            "m"              : self.mobile,
            "pass"           : self.password,
            "captchaCode"    : None,
            "checkCodeKey"   : "null"
        }
        try:
            r = self.session.post(self.host+"/im5/login/loginHtml5.action", data=login_payload)
        except:
            raise ConnError("%11s - ConnError: Login" % self.mobile)

        self.id = json.loads(r.text)["idUser"]
        if not self.id:
            raise AuthError("%11s - AuthError: Wrong Mobile or Password" % self.mobile)

    def send_sms(self, msg):
        '''/im5/chat/sendNewGroupShortMsg.action
        :msg
        :touserid

        return sendCode
               0    - 发送失败
               200  - 发送成功'''
        if not self.id:
            raise AuthError("%11s - AuthError: Not Logged In" % self.mobile)

        msg_payload = {
            "msg"       : msg,
            "touserid"  : self.id
        }

        try:
            r = self.session.post(self.host+"/im5/chat/sendNewGroupShortMsg.action", data=msg_payload)
        except:
            raise ConnError("%11s - ConnError: Send SMS" % self.mobile)

        return json.loads(r.text)["sendCode"]

    def logout(self):
        '''/im5/index/logoutsubmit.action'''
        try:
            r = self.session.get(self.host+"/im5/index/logoutsubmit.action")
        except:
            ConnError("%11s - ConnError: Logout" % self.mobile)
        self.id = None
