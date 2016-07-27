#!/usr/bin/env/python

import lxml.html
import requests

import os.path

import slackweb

from lxml import html

from urllib.parse import urlparse, parse_qs

from datetime import datetime as dt

import configparser
import json

from logging import getLogger
import logging.config
import traceback

logger = getLogger(__name__)
logging.basicConfig(filename='/tmp/drv_parser.log',level=logging.DEBUG)

class AutoVivification(dict):
    """Implementation of perl's autovivification feature. Has features from both dicts and lists,
    dynamically generates new subitems as needed, and allows for working (somewhat) as a basic type.
    """
    def __getitem__(self, item):
        if isinstance(item, slice):
            d = AutoVivification()
            items = sorted(self.iteritems(), reverse=True)
            k,v = items.pop(0)
            while 1:
                if (item.start < k < item.stop):
                    d[k] = v
                elif k > item.stop:
                    break
                if item.step:
                    for x in range(item.step):
                        k,v = items.pop(0)
                else:
                    k,v = items.pop(0)
            return d
        try:
            return dict.__getitem__(self, item)
        except KeyError:
            value = self[item] = type(self)()
            return value

    def __add__(self, other):
        """If attempting addition, use our length as the 'value'."""
        return len(self) + other

    def __radd__(self, other):
        """If the other type does not support addition with us, this addition method will be tried."""
        return len(self) + other

    def append(self, item):
        """Add the item to the dict, giving it a higher integer key than any currently in use."""
        largestKey = sorted(self.keys())[-1]
        if isinstance(largestKey, str):
            self.__setitem__(0, item)
        elif isinstance(largestKey, int):
            self.__setitem__(largestKey+1, item)

    def count(self, item):
        """Count the number of keys with the specified item."""
        return sum([1 for x in self.items() if x == item])

    def __eq__(self, other):
        """od.__eq__(y) <==> od==y. Comparison to another AV is order-sensitive
        while comparison to a regular mapping is order-insensitive. """
        if isinstance(other, AutoVivification):
            return len(self)==len(other) and self.items() == other.items()
        return dict.__eq__(self, other)

    def __ne__(self, other):
        """od.__ne__(y) <==> od!=y"""
        return not self == other

class Kyoshu(object):

	def __init__(self):
		inifile = configparser.SafeConfigParser()
		inifile.read('./config.ini')

		self.m_user=inifile.get('identifier','user_no')
		self.m_passwd=inifile.get('identifier','user_password')
		self.url_base=inifile.get('greserve','url_base')
		self.url_login=inifile.get('greserve','url_login')
		self.m_base_url=inifile.get('greserve','mobile_url')

		self.file_schedule_all=inifile.get('file','schedule_all')
		self.file_reserve=inifile.get('file','reserve')

		self.slack_integration=inifile.get('greserve','slack_integration')

		self.session_requests = requests.session()
		self.slack = slackweb.Slack(url=self.slack_integration)
		self.logged_in=False

	def __call__(self):
		self.__init__()

	def do_login(self):
		if self.logged_in==True:
			return True
		r = self.session_requests.get(self.m_base_url)
		payload = {
			"b.schoolCd" : "xaFIWet1fi0+brGQYS+1OA==",
			"server" : "el25aspa",
			"b.studentId" : self.m_user,
			"b.password" : self.m_passwd,
			"method:doLogin" : '1'
		}
		result = self.session_requests.post(
			self.url_login,
			data = payload,
			headers = dict(referer=self.m_base_url))
		result.encoding = 'Shift_JIS'
		dom = html.fromstring(result.text)
		link_doms=dom.xpath('//a')

		operations=[]
		for dom in link_doms:
			b={}
			b['action_ja']=dom.text
			b['url']=dom.attrib['href']
			operations.append(b)
		self.operations=operations
		self.logged_in=True
		return True

	def _notify(self,text):
		self.slack.notify(text=text)

	def _filter_operations_by_name(self,name):
		self.do_login()
		operations=self.operations
		for ops in operations:
			if ops['action_ja'] == '技能予約':
				url=ops['url']
				return self.url_base+url
		return False

	def _filter_string_by_date(self,string,month,day):
		if month+'月' in string and day+'日' in string:
			return True

	def _filter_dom_by_date(self,doms,month,day):
		for dom in doms:
			if self._filter_string_by_date(dom.text,month,day):
				return dom
		return False

	def do_reserve(self,month,day,hour):
		#特定の時限の予約を行う
		url = None
		#指導員の名前(予約時指定のときのみ入る)
		sh_name = None

		g = self.get_reserve_page(month,day)
		for each in g:
			each_hour = each.get('hour',{})
			each_url = each.get('url',{})
			if str(hour)==str(each_hour):
				url=each_url
				break

		if url is None:
			self._notify('予約不能: ('+str(month)+'/'+str(day)+' '+str(hour)+'限) は予約できる状態ではありません。')
			return False

		r = self.session_requests.get(url)
		r.encoding='Shift_JIS'

		#指名できるかどうかチェック
		dom = html.fromstring(r.text.strip())
		font_title=dom.xpath("//font[@class='headerTitle']")
		#指名できそう
		if len(font_title)!=0 and font_title[0].text=='指名変更':
			link_doms = dom.xpath('//a')
			list=[]
			for dom in link_doms:
				b={}
				#指名チェック
				if 'm03j' in dom.attrib['href'] and 'selectInstructorCd=-1' not in dom.attrib['href']:

					b['name']=dom.text
					b['url']=self.url_base+dom.attrib['href']
					list.append(b)

			#1人目の人を指名する
			r = self.session_requests.get(list[0]['url'])
			sh_name = list[0]['name']
			r.encoding='Shift_JIS'


		#指名がなければ / or 指名後のページ
		dom = html.fromstring(r.text.strip())
		form_dom=dom.xpath('//form')[0]

		action = form_dom.action

		input_dom=dom.xpath('//form/input')
		payload = {}

		#hidden パラメータを読み込んで送るようにする
		for dom in input_dom:
			if 'b.' in dom.name or 'token' in dom.name or 'struts.token.name' in dom.name:
				payload[dom.name] = dom.value

		payload['method:doYes'] = 1

		r = self.session_requests.post(
			self.url_base+action,
			data = payload
		)
		r.encoding='Shift_JIS'
		dom = html.fromstring(r.text.strip().replace('BR', '').replace('br', ''))
		#fetch error
		font_dom_ok=dom.xpath("//font[@class='ok']")
		font_dom_error=dom.xpath("//font[@class='error']")
		if len(font_dom_ok) != 0 and font_dom_ok[0].text is not False:
			self._notify('[成功]予約成功: ('+str(month)+'/'+str(day)+' '+str(hour)+'限) を予約しました')
			if sh_name is not None:
				self._notify('指名指導員: '+sh_name)
		elif len(font_dom_error) != 0 and font_dom_error[0].text is not False:
			self._notify('予約エラー: ('+str(month)+'/'+str(day)+' '+str(hour)+'限) '+font_dom_error[0].text)
		else:
			self._notify('例外発生: ('+str(month)+'/'+str(day)+' '+str(hour)+'限) 予約のステータスを確認してください')



	def get_reserve_page(self,month,day):
		#その日にちの予約URL一覧を取得
		r = self.session_requests.get(self._filter_operations_by_name('技能予約'))
		r.encoding='Shift_JIS'
		dom = html.fromstring(r.text.strip())
		link_doms=dom.xpath('//a')
		dom = self._filter_dom_by_date(link_doms,month,day)

		#日付ごとの予約ページを取得する
		r = self.session_requests.get(self.url_base+dom.attrib['href'])
		r.encoding='Shift_JIS'
		dom = html.fromstring(r.text.strip())
		link_doms=dom.xpath('//a')
		list=[]
		for dom in link_doms:
			b={}
			#時間指定のものを抜く
			if '○' in dom.text or '×' in dom.text or 'Ｓ' in dom.text:
				u= parse_qs(urlparse(self.url_base+dom.attrib['href']).query)
				b['hour']=u.get('b.infoPeriodNumber', [''])[0]
				b['url']=self.url_base+dom.attrib['href']
				list.append(b)
		return list


	def get_page_reservation(self):
		url=self._filter_operations_by_name('技能予約')
		r = self.session_requests.get(url)
		r.encoding='Shift_JIS'
		dom = html.fromstring(r.text.strip())
		link_doms=dom.xpath('//a')

		#next week
		for dom in link_doms:
			if '前週' in dom.text:
				prev=self.url_base+dom.attrib['href']
			elif '次週' in dom.text:
				next=self.url_base+dom.attrib['href']
		list=[]

		for u in [url,next]:
			r = self.session_requests.get(u)
			r.encoding='Shift_JIS'
			dom = html.fromstring(r.text.strip())
			link_doms=dom.xpath('//a')

			for dom in link_doms:
				b={}
				b['date']=dom.text
				b['resinfo']=str(dom.getnext().tail).strip().replace(' ','')
				b['schedule']=self._convert_schedule_string_to_obj(b['resinfo'])

				if '月' in b['date'] and '日' in b['date']:
					list.append(b)

		self._compare_schedule(list)
		self._save_schedule_to_file(list)
		return list

	def _compare_schedule(self,dict):
		saved_dict = self._open_schedule_from_file()
		if saved_dict == False:
			return False

		while (saved_dict[0]['date'] != dict[0]['date']):
			saved_dict.pop(0)

		for saved_date_dict,date_dict in zip(saved_dict,dict):
			date=date_dict['date']
			print('check for '+date)

			d = dt.today()
			tdatetime = dt.strptime(str(d.year)+'年'+date[0:6], '%Y年%m月%d日')
			short_m=tdatetime.strftime('%m')
			short_d=tdatetime.strftime('%d')

			for saved_hours,hours in zip(saved_date_dict['schedule'],date_dict['schedule']):
				if saved_hours['description'] != hours['description']:
					if(hours['description']=='Available' or hours['description']=='Available[S]'):
						self._notify('[空き]'+date+' '+str(hours['hour'])+'限の予約ができるようになりました (state has changed from '+saved_hours['description']+' to '+hours['description']+')')
						self.check_and_do_reserve(short_m,short_d,hours['hour'])
					elif(hours['description']=='Unavailable'):
						self._notify(date+' '+str(hours['hour'])+'限は、予約されてしまいました。 (state has changed from '+saved_hours['description']+' to '+hours['description']+')')
					elif(hours['description']=='Reserved'):
						self._notify(date+' '+str(hours['hour'])+'限は、あなたが予約しました。 (state has changed from '+saved_hours['description']+' to '+hours['description']+')')
					else:
						self._notify('Date: '+date+' Hour:'+str(hours['hour'])+' state has changed from '+saved_hours['description']+' to '+hours['description'])

	def check_and_do_reserve(self,month,day,hour):
		if self.check_reserve(str(month),str(day),str(hour)) == True:
			self._notify('予約対象として登録されているので、予約を試行します')
			return self.do_reserve(month,day,hour)
		else:
			return False

	def add_new_reserve(self,month,day,hour):
		month=month.zfill(2)
		day=day.zfill(2)
		dict=self._open_reserve_from_file()
		if dict is False:
			#新規作成
			dict = AutoVivification()
		else:
			dict = AutoVivification(self._open_reserve_from_file())

		if len(dict[month]) >= 1:
			#その日に既に登録があったら、保持する
			if len(dict[month][day]) >= 1:
				day_dict = dict[month][day]
				day_dict.update({hour: 1})
			else:
			#その日に登録がなければ、新規作成
				dict[month].update({day: {hour: 1}})
		else:
			dict[month][day][hour] = 1

		return self._save_reserve_to_file(dict)

	def del_reserve(self,month,day,hour):
		month=month.zfill(2)
		day=day.zfill(2)
		dict=self._open_reserve_from_file()
		if dict is False:
			#新規作成
			dict = AutoVivification()
		else:
			dict = AutoVivification(self._open_reserve_from_file())

		if len(dict[month]) >= 1:
			#その日に既に登録があったら、保持する
			if len(dict[month][day]) >= 1:
				day_dict = dict[month][day]
				day_dict.update({hour: -1})
			else:
			#その日に登録がなければ、新規作成
				dict[month].update({day: {hour: -1}})
		else:
			dict[month][day][hour] = 1
		return self._save_reserve_to_file(dict)

	def check_reserve(self,month,day,hour):
		month=month.zfill(2)
		day=day.zfill(2)
		dict=self._open_reserve_from_file()
		if dict is False:
			return False
		else:
			dict = AutoVivification(self._open_reserve_from_file())
		try:
			#一度エラー処理で逃げる
			if len(dict[month]) >= 1:
				if len(dict[month][day]) >= 1:
					if hour in dict[month][day]:
						return True
			return False
		except:
			return False

	def _open_reserve_from_file(self):
		if (os.path.exists(self.file_reserve)==False):
			return False

		with open(self.file_reserve,'r') as f:
			return json.load(f)

	def _save_reserve_to_file(self,dict):
		with open(self.file_reserve,'w') as f:
			json.dump(dict, f, sort_keys=True, indent=4)

	def _save_schedule_to_file(self,dict):
		with open(self.file_schedule_all,'w') as f:
			json.dump(dict, f, sort_keys=True, indent=4)

	def _open_schedule_from_file(self):
		if (os.path.exists(self.file_schedule_all)==False):
			return False

		with open(self.file_schedule_all,'r') as f:
			return json.load(f)

	def _convert_schedule_string_to_obj(self,string):
		strlist=[]
		strlist=list(str(string))
		schedule_list=[]
		desc=''
		h=1
		for m in strlist:
			d={}
			if m=='X':
				#枠はあるが、予約で一杯
				desc='Unavailable'
			elif m=='J':
				#予約済み
				desc='Reserved'
			elif m=='O':
				#予約可能
				desc='Available'
			elif m=='-':
				#そもそも枠がない
				desc='Unavailable'
			elif m=='K':
				#検定予約済み
				desc='Test'
			elif m=='G':
				desc='Desk Reserved'
			elif m=='S':
				#指名予約可
				desc='Available[S]'

			d['hour']=h
			d['str']=m
			d['description']=desc

			schedule_list.append(d)
			h=h+1
		return schedule_list



def main():
	Kyoshu.get_page_reservation()
	#Kyoshu.do_reserve('8','1','2')

if __name__ == '__main__':
	logger.info('start')
	try:
		Kyoshu = Kyoshu()
		main()
	except:
		logger.error(traceback.format_exc())
	logger.info('End')
