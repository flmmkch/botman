#!/usr/bin/python3

import os, sys, time, random
import apsw
import unicodedata

DBFILENAME='botman.sqlite'
MAX_SENTENCE = 320
# reply rate : int between 0 and 100
SETTINGS_REPLY_RATE_KEY = 'REPLY_RATE'
SETTINGS_DEFAULT_REPLY_RATE = 25
REPLY_RATE_HIGHLIGHT_MULTIPLIER = 3

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

class ReadStringResult:
	def __init__(self, words = []):
		self.words = words
		self.reply_rate_multiplier = 1
	def last_word(self):
		if len(self.words) > 0:
			return self.words[-1]
		return None
	def first_word(self):
		if len(self.words) > 0:
			return self.words[0]
		return None

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
	# Get the reply rate as a percentage
	def get_reply_rate_from_db(self):
		reply_rate_string_res = self.dbc.cursor().execute("select sval from settings where skey = ?;", (SETTINGS_REPLY_RATE_KEY,)).fetchone()
		if reply_rate_string_res:
			reply_rate = int(reply_rate_string_res[0])
			return reply_rate
		return SETTINGS_DEFAULT_REPLY_RATE
	# Reading and processing a string
	def readstring(self, string):
		if len(string) == 0:
			return ReadStringResult()
		cursor = self.dbc.cursor()
		rw = [raw_word for raw_word in string.split(' ')]
		rw_tuples = [(raw_word,) for raw_word in rw]
		cursor.execute("begin;")
		cursor.executemany("insert or ignore into words(word) values(?);", rw_tuples)
		cursor.execute("commit;")
		# For each word we add an occurence with the preceding word
		updatebindings = []
		preceding = -1
		for wordid, in cursor.executemany("select rowid from words where word = ?;", rw_tuples):
			updatebindings.append((preceding, wordid, preceding, wordid))
			preceding = wordid
		# Then we add the sentence ending occurence (-1)
		updatebindings.append((preceding, -1, preceding, -1))
		cursor = self.dbc.cursor()
		cursor.execute("begin;")
		cursor.executemany("insert or ignore into seqs(prevword, nextword) values(?, ?); update seqs set occurences = occurences + 1 where prevword = ? and nextword = ?;", updatebindings)
		cursor.execute("commit;")
		return ReadStringResult(rw)
	# decide whether this should be a reply or not according to the reply rate
	def decide_reply_dice_throw(self, reply_rate_multiplier = 1):
		reply_rate = self.get_reply_rate_from_db()
		randomnumber = self.sr.randint(1, 100)
		final_reply_rate = reply_rate * reply_rate_multiplier
		return randomnumber < final_reply_rate
	def get_rowid_for_word(self, word):
		presumed_wid = self.dbc.cursor().execute("select rowid from words where word = ?;", (word,)).fetchone()
		if presumed_wid:
			return presumed_wid[0]
		return None
	def add_word_to_sentence(self, sentence, word, wid, invert):
		finished = False
		if wid >= 0 and word:
			if invert:
				if len(sentence) > 0:
					sentence = ' ' + sentence
				sentence = word + sentence
			else:
				if len(sentence) > 0:
					sentence += ' '
				sentence += word
			if len(sentence) > MAX_SENTENCE:
				finished = True
		else:
			finished = True
		return (sentence, finished)
	# Generating a new string, optionally with a given base sentence and optionally starting with the last word
	def generatestring(self, sentence = '', invert = False, read_result = None):
		wid = -1
		wordcount = 0
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
			wid = self.get_rowid_for_word(wordlist[startword]) or wid
		elif read_result and self.decide_reply_dice_throw(read_result.reply_rate_multiplier):
			start_word_string = None
			if invert:
				start_word_string = read_result.first_word()
			else:
				start_word_string = read_result.last_word()
			wid = self.get_rowid_for_word(start_word_string) or wid
			wordcount += 1
			(sentence, finished) = self.add_word_to_sentence(sentence, start_word_string, wid, invert)
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
			# if there is only the end of the sentence available but we're just starting to generate it then we'll try to generate something from scratch
			if wordcount == 0 and len(nwchoices) == 1 and nwchoices[0][2] == -1:
				wid = -1
				continue
			# Quit if there's no choice
			elif totaloccurences == 0:
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
				if word != None and wordcount <= 0 and word[2] <= -1:
					word = None
			# Adding the word to the sentence
			wid = word[2]
			wordcount += 1
			(sentence, finished) = self.add_word_to_sentence(sentence, word[0], wid, invert)
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
		read_result = None
		if message[0] == self.COMMAND_SIGN:
			arguments = message.split(' ')
			command = arguments[0][len(self.COMMAND_SIGN):]
			if command == self.COMMAND_SENTENCE:
				if len(command) > 1:
					self.sendnewsentence(conversationid, message[len(self.COMMAND_SIGN + command):], False, read_result, userparams)
				else:
					self.sendnewsentence(conversationid, '', False, read_result, userparams)
			elif command == self.COMMAND_SENTENCE_INV:
				self.sendnewsentence(conversationid, message[len(self.COMMAND_SIGN + command):], True, read_result, userparams)
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
					read_result = self.corebot.readstring(message)
				else:
					read_result = ReadStringResult(message.split(' '))
				read_result.reply_rate_multiplier = REPLY_RATE_HIGHLIGHT_MULTIPLIER
				self.sendnewsentence(conversationid, '', False, read_result, userparams)
			else:
				read_result = self.corebot.readstring(message)
				self.counter[conversationid] -= 1
				if self.counter[conversationid] <= 0:
					self.sendnewsentence(conversationid, '', False, read_result, userparams)
					self.initcounter(conversationid)
	def sendnewsentence(self, target, base = '', invert = False, read_result = None, userparams = None):
		return self.corebot.generatestring(base, invert, read_result)
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

