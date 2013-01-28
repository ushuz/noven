# -*- coding:utf-8 -*-

import json
import requests


class Fetion(object):
    '''A simplified 3G Fetion.
    Only reserved login(), send(), logout().'''
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
        r = self.session.post(self.host+"/im5/login/loginHtml5.action", data=login_payload)
        self.id = json.loads(r.text)["idUser"]
        return r
    
    def send(self, msg):
        '''/im5/chat/sendNewGroupShortMsg.action
        :msg
        :touserid'''
        if not self.id:
            return
        msg_payload = {
            "msg":msg,
            "touserid":self.id
        }
        r = self.session.post(self.host+"/im5/chat/sendNewGroupShortMsg.action", data=msg_payload)
        return r
    
    def logout(self):
        '''/im5/index/logoutsubmit.action'''
        r = self.session.get(self.host+"/im5/index/logoutsubmit.action")
        return r