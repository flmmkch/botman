#!/usr/bin/python3

import os, sys, time, random
import apsw
import irc, irc.bot
import unicodedata

DBFILENAME='botman.sqlite'
MAX_SENTENCE = 320

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
	def __contains__(self, a):
		return a in self.s

class BotmanCore:
	def __init__(self, dbconnection):
		self.dbc = dbconnection
		self.sr = random.SystemRandom()
	# Initializing the SQLite database
	@staticmethod
	def dbinit(connection):
		connection.cursor().execute("create table settings(skey text primary key not null, sval text); \
									create table words(word text primary key not null); \
									create table seqs(prevword int, nextword int, occurences int default 0, primary key(prevword, nextword)); \
									create index widx on words(word); \
									create index wseq on seqs(prevword, nextword);")
	# Reading and processing a string
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
	# Generating a new string, optionally with a given base sentence and optionally starting with the last word
	def generatestring(self, sentence = '', invert = False):
		wid = -1
		# if the given base sentence is not empty
		# we split the words and find out their database identifiers
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
			if wid >= 0 and word[0]:
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


class BotmanInterface:
	COMMAND_SIGN = '/'
	COMMAND_SENTENCE = 'phrase'
	COMMAND_SENTENCE_INV = 'phraseinv'
	MODE_RUN = 0
	MODE_CONFIGURE = 1
	MODE_INIT = 2
	MODE_FEED = 3
	MODE_HELP = 4
	def __init__(self, arguments = sys.argv):
		self.mode = self.MODE_RUN
		if len(arguments) > 1:
			if arguments[1] == 'init':
				self.mode = self.MODE_INIT
			elif arguments[1] == 'config':
				self.mode = self.MODE_CONFIGURE
			elif arguments[1] == 'help':
				self.mode = self.MODE_HELP
			elif arguments[1] == 'feed':
				self.mode = self.MODE_FEED
				self.filestofeed = arguments[2:]
		self.running = True
		if self.mode != self.MODE_INIT and not os.path.exists(DBFILENAME):
			print('Launch the script with the parameter "init" to initialize the database first')
			self.running = False
			return
		if self.mode == self.MODE_INIT:
			# Deleting the SQLite file to fully reset the database
			if os.path.exists(DBFILENAME):
				os.remove(DBFILENAME)
		self.dbc = apsw.Connection(DBFILENAME)
		if self.mode == self.MODE_INIT:
			BotmanCore.dbinit(apsw.Connection(DBFILENAME))
		self.settings = SettingGroup(self.dbc)
		self.corebot = BotmanCore(self.dbc)
		self.sr = random.SystemRandom()
		# Counter for the random sentences
		self.counter = {}
		# Aliases that the bot responds to
		self.aliases = []
		if 'aliases' in self.settings:
			for alias in self.settings['aliases'].split(','):
				alias = alias.strip().lower()
				if len(alias) > 0:
					self.aliases.append(alias)
	def initcounter(self, conversationid):
		self.counter[conversationid] = self.sr.randint(15, 25)
	# Receive a message
	def receivemessage(self, message, conversationid, userparams = None):
		if not conversationid in self.counter:
			self.initcounter(conversationid)
		if message[0] == self.COMMAND_SIGN:
			arguments = message.split(' ')
			command = arguments[0][len(self.COMMAND_SIGN):]
			if command == self.COMMAND_SENTENCE:
				if len(command) > 1:
					self.sendnewsentence(conversationid, message[len(self.COMMAND_SIGN + command):], False, userparams)
				else:
					self.sendnewsentence(conversationid, '', False, userparams)
			elif command == self.COMMAND_SENTENCE_INV:
				self.sendnewsentence(conversationid, message[len(self.COMMAND_SIGN + command):], True, userparams)
		else:
			# Reading the current message
			lowermsg = str(message).lower()
			highlighted = False
			for alias in self.aliases:
				if alias in lowermsg:
					highlighted = True
					break
			if highlighted:
				if 'highlightlearn' not in self.settings or self.settings['highlightlearn'][0].lower() != 'n':
					self.corebot.readstring(message)
				self.sendnewsentence(conversationid, '', False, userparams)
			else:
				self.corebot.readstring(message)
				self.counter[conversationid] -= 1
				if self.counter[conversationid] <= 0:
					self.sendnewsentence(conversationid, '', False, userparams)
					self.initcounter(conversationid)
	def sendnewsentence(self, target, base = '', invert = False, userparams = None):
		sentence = self.corebot.generatestring(base, invert)
		return sentence
	def display_help(self):
		print('Usage: ./botman.py [optional command]')
		print('List of special commands:')
		print('* help to print this help')
		print('* init to initialize the database and configuration then launch the bot for the first time')
		print('* config to only change the configuration of the bot, such as IRC settings')
		print('* feed [filename] to feed a text file to the database')
	def configure(self):
		if 'aliases' in self.settings:
			print('Current aliases:', self.settings['aliases'])
		aliases = input('Aliases (separated by commas, empty = unchanged, . = empty): ')
		if aliases == '.':
			self.settings['aliases'] = ''
		elif len(aliases) > 0:
			self.settings['aliases'] = aliases
		if 'highlightlearn' not in self.settings:
			questionstring = 'Learn messages calling to the bot? (Y/n, empty = unchanged): '
		else:
			questionstring = 'Learn messages calling to the bot? (Y/n, empty = unchanged from ' + self.settings['highlightlearn'] + '): '
		highlightlearn = input(questionstring).strip()
		if len(highlightlearn) > 0:
			self.settings['highlightlearn'] = highlightlearn
	def feed_db(self):
		for filename in self.filestofeed:
			with open(filename, 'r', encoding='utf-8') as infile:
				for line in infile:
					stripped = line.replace("\r", "").replace("\t", " ").strip()
					if len(stripped) > 0:
						self.corebot.readstring(stripped)
	def run(self):
		if self.running:
			if self.mode == self.MODE_INIT:
				self.configure()
			elif self.mode == self.MODE_CONFIGURE:
				self.configure()
				self.running = False
			elif self.mode == self.MODE_HELP:
				self.display_help()
				self.running = False
			elif self.mode == self.MODE_FEED:
				self.feed_db()
				self.running = False
		return self.running
	def close(self):
		self.dbc.close()

