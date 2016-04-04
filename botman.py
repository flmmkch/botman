#!/usr/bin/python3

import os, sys, time, random
import apsw
import irc, irc.bot
import unicodedata

DBFILENAME='botman.sqlite'
MAX_SENTENCE = 320

def dbinit(connection):
	connection.cursor().execute("create table settings(skey text primary key not null, sval text); \
					create table words(word text primary key not null); \
					create table seqs(prevword int, nextword int, occurences int default 0, primary key(prevword, nextword)); \
					create index widx on words(word); \
					create index wseq on seqs(prevword, nextword);")

class SettingGroup:
	def __init__(self, connection):
		self.c = connection
		self.s = {}
		self.retrieve()
	def retrieve(self):
		self.s = {}
		kvpairs = self.c.cursor().execute("select skey, sval from settings")
		for i in kvpairs:
			self.s[str(i[0])] = i[1]
	def __getitem__(self, item):
		return self.s[item]
	def __setitem__(self, key, value):
		self.c.cursor().execute("insert or replace into settings(skey, sval) values(?, ?)", (key, value))
		self.s[key] = value

class Botman:
	def __init__(self, settings, dbconnection):
		self.settings = settings
		self.dbc = dbconnection
		self.sr = random.SystemRandom()
	def readstring(self, string):
		if len(string) == 0:
			return
		cursor = self.dbc.cursor()
		rw = []
		for rawword in string.split(' '):
			rw.append((rawword,))
		cursor.execute("begin;")
		cursor.executemany("insert or ignore into words(word) values(?);", rw)
		cursor.execute("commit;")
		# For each word we add an occurence with the preceding word
		updatebindings = []
		preceding = -1
		for wordid, in cursor.executemany("select rowid from words where word = ?;", rw):
			updatebindings.append((preceding, wordid, preceding, wordid))
			preceding = wordid
		# Then we add the sentence ending occurence (-1)
		updatebindings.append((preceding, -1, preceding, -1))
		cursor = self.dbc.cursor()
		cursor.execute("begin;")
		cursor.executemany("insert or ignore into seqs(prevword, nextword) values(?, ?); update seqs set occurences = occurences + 1 where prevword = ? and nextword = ?;", updatebindings)
		cursor.execute("commit;")
	def generatestring(self, sentence = '', invert = False):
		wid = -1
		# if the sentence given is not empty
		if len(sentence) > 0:
			sentence = sentence.strip()
			# begin the random part with the last word of the sentence
			wordlist = sentence.split(' ')
			if invert:
				startword = 0
			else:
				startword = -1
			presumed_wid = self.dbc.cursor().execute("select rowid from words where word = ?;", (wordlist[startword],)).fetchone()
			if presumed_wid:
				wid = presumed_wid[0]
		finished = False
		while not finished:
			if invert:
				nwquery = "select prevword, occurences from seqs where nextword = ?;"
			else:
				nwquery = "select nextword, occurences from seqs where prevword = ?;"
			nwchoices = []
			totaloccurences = 0
			for nwid, occurences in self.dbc.cursor().execute(nwquery, (wid,)):
				nextword = None
				if nwid >= 0:
					result =  self.dbc.cursor().execute("select word from words where rowid = ?", (nwid,)).fetchone()
					if result:
						nextword = result[0]
				nwchoices.append((nextword, occurences, nwid))
				totaloccurences += occurences
			# Quit if there's no choice
			if totaloccurences == 0:
				return sentence
			# Weighted random for actually picking the next word
			word = None
			while not word:
				randomnumber = self.sr.randint(0, totaloccurences - 1)
				noccurences = 0
				for choice in nwchoices:
					noccurences += choice[1]
					if noccurences > randomnumber:
						word = choice
						break
			# Adding the word to the sentence
			wid = word[2]
			if wid >= 0:
				if invert:
					if len(sentence) > 0:
						sentence = ' ' + sentence
					sentence = word[0] + sentence
				else:
					if len(sentence) > 0:
						sentence += ' '
					sentence += word[0]
				if len(sentence) > MAX_SENTENCE:
					finished = True
			else:
				finished = True
		return sentence

class IRCBotman(irc.bot.SingleServerIRCBot):
	def __init__(self, settings, dbconnection):
		self.settings = settings
		self.dbc = dbconnection
		self.sr = random.SystemRandom()
		self.botman = Botman(settings, dbconnection)
		self.initcounter()
		irc.bot.SingleServerIRCBot.__init__(self, [(self.settings['server'], int(self.settings['port']))], self.settings['nick'], self.settings['nick'])
	def initcounter(self):
		self.counter = self.sr.randint(15, 25)
	def on_nicknameinuse(self, c, e):
		c.nick(self.settings['nick2'])
	def on_welcome(self, c, e):
		c.join(self.settings['channel'])
	def on_pubmsg(self, c, e):
		self.reply(c, e, e.target)
	def on_privmsg(self, c, e):
		nick = e.source[:e.source.find('!')]
		self.reply(c, e, nick)
	def on_join(self, c, e):
		print('Joining channel', e.target)
	def on_kick(self, c, e):
		if e.target == self.settings['channel'] and e.arguments[0] == c.get_nickname():
			c.join(self.settings['channel'])
	def reply(self, c, e, target):
		msg = e.arguments[0]
		if msg[0] == '!':
			command = msg.split(' ')
			if command[0] == '!phrase':
				if len(command) > 1:
					self.sendnewsentence(c, target, msg[len(command[0]):])
				else:
					self.sendnewsentence(c, target)
			elif command[0] == '!phraseinv' and len(command) > 1:
				self.sendnewsentence(c, target, msg[len(command[0]):], True)
		else:
			self.botman.readstring(msg)
			if str(c.get_nickname()).lower() in str(msg).lower():
				self.sendnewsentence(c, target)
			else:
				self.counter -= 1
				if self.counter <= 0:
					self.sendnewsentence(c, target)
					self.initcounter()
	def sendnewsentence(self, c, target, msg = None, invert = False):
		sentence = ''
		if msg:
			sentence = self.botman.generatestring(msg, invert)
		else:
			sentence = self.botman.generatestring()
		c.privmsg(target, sentence.replace("\r","").replace("\n",""))

irc.client.ServerConnection.buffer_class = irc.buffer.LenientDecodingLineBuffer

def configure():
	connection=apsw.Connection(DBFILENAME)
	settings = SettingGroup(connection)
	print('IRC server:')
	settings['server'] = input('> ').strip()
	print('Port: (if empty, 6667)')
	port = input('> ').strip()
	if port == '':
		settings['port'] = 6667
	else:
		settings['port'] = port
	print('Nickname:')
	settings['nick'] = input('> ').strip()
	settings['nick2'] = settings['nick'] + '_'
	print('Channel:')
	settings['channel'] = input('> ').strip()
	connection.close()

def display_help():
	print('Usage: ./botman.py [optional command]')
	print('List of special commands:')
	print('* help to print this help')
	print('* init to initialize the database and configuration then launch the bot for the first time')
	print('* config to only change the configuration of the bot, such as IRC settings')
	print('* feed [filename] to feed a text file to the database')

def feed_db(filenames):
	connection=apsw.Connection(DBFILENAME)
	botman = Botman(SettingGroup(connection), connection)
	slist = []
	for filename in filenames:
		with open(filename, 'r', encoding='utf-8') as infile:
			for line in infile:
				if len(line) > 0:
					slist.append(line.replace("\r", "").replace("\n", "").replace("\t", " "))
	for sentence in slist:
		botman.readstring(sentence)
	connection.close()

if len(sys.argv) > 1:
	if sys.argv[1] == 'init':
		if os.path.exists(DBFILENAME):
			os.remove(DBFILENAME)
		connection=apsw.Connection(DBFILENAME)
		dbinit(connection)
		connection.close()
	if sys.argv[1] in ['init', 'config']:
		configure()
	elif sys.argv[1] == 'help':
		display_help()
	elif sys.argv[1] == 'feed':
		feed_db(sys.argv[2:])
	if sys.argv[1] in ['config', 'help', 'feed']:
		sys.exit()
if not os.path.exists(DBFILENAME):
	print('Launch the script with the parameter "init" to initialize the database first')
	sys.exit()
connection=apsw.Connection(DBFILENAME)
settings = SettingGroup(connection)
nbm = IRCBotman(settings, connection)
nbm.start()
connection.close()
