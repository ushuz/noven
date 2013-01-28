# -*- coding:utf-8 -*-

import os
import urllib2
import logging


class Course(object):
    '''A wrapper of the basic properties of a course.

    Wrap up the basic properties of a course such as SUBJECT, GRADE, etc to
    provide easy accessibility.
    '''
    def __init__(self, subject=None, grade=None, point=None, term=None):
        self.subject = subject   # 课程名称
        self.grade = grade       # 课程成绩
        self.point = point       # 课程学分
        self.term = term         # 课程学期

    def __str__(self):
        unic = u"%-15s\t%s\t%s" % (self.subject, self.grade, self.term)
        return unic.encode((os.name == 'posix' and 'utf-8' or 'cp936'))
    
    def __unicode__(self):
        unic = u"%-15s\t%s\t%s" % (self.subject, self.grade, self.term)
        return unic


class User(object):
    '''Object that represent a user.

    Providing a bunch of useful methods and store related data of a user.
    '''
    def __init__(self, ucode, upass, mcode=None, mpass=None):
        self.usercode = ucode
        self.password = upass
        self.mobileno = mcode
        self.mobilepass = mpass
        
        self.name = ''
        self.courses = {}
        self.GPA = ''
        self.rank = ''
        self.verified = False
        
        # init original data (name & courses)
        self._cookie = ''
        self.get_cookie()
        self.get_name()
        if self.name:
            self.get_data()         # get original data for later usage

    def _urlopen(self, url, params=None):
        '''Keep trying to open the url until a response is got.'''
        while True:
            try:
                resp = urllib2.urlopen(url, params)
            except:
                continue
            return resp

    def get_cookie(self):
        '''Return the cookie or None if failed.'''
        params = 'type=Logon&B1=+%CC%E1%A1%A1%BD%BB+' + '&UserCode=%s&UserPassword=%s' % (self.usercode, self.password)
        resp = self._urlopen('http://jwxt.bjfu.edu.cn/jwxt/logon.asp', params)
        self._cookie = resp.headers['Set-Cookie'][:-8]

        if self._cookie:
            logging.info('cookie got')
            return self._cookie
        else:
            logging.error('get_cookie() failed')
            return None

    def get_name(self):
        '''Get the real name of the user with cookie.'''
        request = urllib2.Request('http://jwxt.bjfu.edu.cn/jwxt/menu.asp')
        request.add_header('Cookie', self._cookie)
        resp = self._urlopen(request)
        html = resp.read(2200).decode('gb2312')

        import re
        m = re.search(u'''.* MenuItem\( "注销 (.+?)", .*''', html)

        if m is None:
            logging.error('get_name() failed')
            return None
        else:
            self.name = m.groups()[0]
            logging.info('name got - %s' % self.name)
            return self.name

    def get_data(self):
        '''Get all data with cookie.'''
        # download data with cookie
        request = urllib2.Request('http://jwxt.bjfu.edu.cn/jwxt/Student/StudentGraduateInfo.asp')
        request.add_header('Cookie', self._cookie)
        params = 'order=xn&by=DESC&year=0&term=0&keyword=&Submit1=+%B2%E9+%D1%AF+'
        resp = self._urlopen(request, params)
        data = resp.read()

        if data.startswith("<script"):
            logging.error('get_data() failed')
            return None
        else:
            logging.info('data got')

        # import BeautifulSoup to parse the data we got
        from BeautifulSoup import BeautifulSoup
        soup = BeautifulSoup(data)
        l = soup.findAll('tr', height='25')

        # save the GPA & rank calculated by JWXT
        self.GPA = u"全学程" + l[-3].contents[1].contents[1].string.split(u"，")[1].split(u"、")[0]
        self.rank = l[-1].contents[1].contents[2].string if u"全学程" in l[-1].contents[1].contents[2].string else l[-1].contents[1].contents[3].string

        del l[0]    # 删除冗余数据
        del l[-4:]  # 删除冗余数据

        for i in l:
            # parse out normal course info
            if i.contents[1].string != u"&nbsp;" and i.contents[3].get("colspan") != u"5":
                course = Course(
                    subject=i.contents[1].string.replace(u' ', u''),
                    grade=unicode(i.contents[3].contents[0].string),
                    point=i.contents[11].string,
                    term=i.contents[13].string + i.contents[15].string
                )
                self.courses[course.term + course.subject] = course

            # parse out experimental course info
            # generally do not display grade unless ranked
            elif i.contents[3].get('colspan') == u'5':
                course = Course(
                    subject=i.contents[1].string.replace(u' ', u''),
                    grade=u'待评价',
                    point=u'-',
                    term=i.contents[5].string + i.contents[7].string
                )
                self.courses[course.term + course.subject] = course
                # print "%-2s %-35s\t%s\t%s\t%s" % tmp

    def refresh(self):
        '''Compare old data with new data and return newly-released courses.'''
        pre_refresh = self.courses.copy()
        self.get_cookie()
        self.get_data()
        post_refresh = self.courses.copy()

        # post_refresh[u"20121测试课程"] = Course(u"测试课程", u"99", u"3", "20121")
        # print post_refresh
        newly_courses = {}
        for i in list(set(pre_refresh.keys()) ^ set(post_refresh.keys())):
            logging.info(u"a new course picked out - %s", i)
            newly_courses[i] = post_refresh[i]

        logging.info(u"%d courses newly released - %s" % (len(newly_courses), self.name))

        if not newly_courses:
            return None
        else:
            return newly_courses


if __name__ == "__main__":
    logging.basicConfig(format="%(asctime)s - %(levelname)-8s %(message)s", level=logging.DEBUG)
    logging.info("initializing")