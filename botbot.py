import sqlite3
import re
import random
import os.path
import logging

from collections import defaultdict
from dataclasses import dataclass

be = defaultdict(lambda: "is", {"I": "am", "you": "are", "we": "are", "they": "are",})

compliments = ["awesome", "very helpful", "amazing", "great", "brilliant"]

welcomes = ["You're welcome!", "No problem!", "Happy to help!"]

accuse = {"I": "me", "he": "him", "she": "her", "they": "them", "ze": "zir"}


def createdb(db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute(
        "create table bot (id integer primary key, name text unique, pronoun text);"
    )
    c.execute(
        """create table topic (
            bot_id integer,
            topic text,
            foreign key (bot_id) references bot(id),
            unique(bot_id, topic));"""
    )
    return conn


def mention(name):
    return f"@**{ name }**"


def accusative(nominative):
    return accuse.get(nominative, nominative)


def stem(word):
    return re.sub("(s|ings?|ion)$", "", word)


def stemmed_words(text):
    return [
        stem(word.lower())
        for word in re.split(r"\W+", text)
        if word and word.lower() not in common_words
    ]


def pronoun_verb(pronoun, verb):
    if verb == "be":
        return f"{pronoun} {be[pronoun]}"
    return f"{pronoun} {verb}{'s' if pronoun in ('we', 'they') else ''}"


def make_comma_list(words):
    if len(words) == 0:
        return ""
    return ", ".join(words[:-1]) + " and " + words[-1]


def parse_introduction(content):
    match = re.search(
        r"introduce.+?to @(?:\*\*(.+?)\*\*|(\w+))\s*[,.] (\w+) .*?about (.+?)(?:\.|$)",
        content,
        re.IGNORECASE,
    )

    if match:
        (name1, name2, pronoun, topics) = match.groups()
        if pronoun == "you":
            pronoun = "I"
        else:
            pronoun = pronoun.lower()
        topics = stemmed_words(topics)
        return Bot(name=(name1 or name2), pronoun=pronoun, topics=topics)


@dataclass
class Bot:
    name: str
    pronoun: str
    topics: list


class BotDatabase:
    def __init__(self, db_path):
        if os.path.exists(db_path):
            self.connection = sqlite3.connect(db_path)
        else:
            self.connection = createdb(db_path)

    def add_bot(self, bot):
        try:
            c = self.connection.cursor()
            c.execute(
                "insert into bot (name, pronoun) values (?, ?)", (bot.name, bot.pronoun)
            )
            bot_id = c.lastrowid
            new = True
        except sqlite3.IntegrityError:
            c = self.connection.cursor()
            c.execute("select id from bot where name = bot.name")
            (bot_id,) = c.fetchone()
            new = False
        new_topics = []
        for topic in bot.topics:
            try:
                c = self.connection.cursor()
                c.execute(
                    "insert into topic (bot_id, topic) values (?, ?)", (bot_id, topic)
                )
            except sqlite3.IntegrityError:
                continue
            new_topics.append(topic)

        self.connection.commit()
        return new, new_topics

    def bots(self):
        c = self.connection.cursor()
        c.execute("select name, pronoun from bot")
        return (Bot(name=row[0], pronoun=row[1], topics=[]) for row in c)

    def lookup_topic(self, topic):
        c = self.connection.cursor()
        c.execute(
            "select name, pronoun from bot join topic on bot.id = topic.bot_id where topic = ?",
            (topic,),
        )
        try:
            (name, pronoun) = c.fetchone()
        except TypeError:
            return None
        return Bot(name=name, pronoun=pronoun, topics=[topic])

    def lookup_bot(self, name):
        c = self.connection.cursor()
        c.execute(
            "select name, pronoun from bot where name = ?", (name,),
        )
        try:
            (name, pronoun) = c.fetchone()
        except TypeError:
            return None
        return Bot(name=name, pronoun=pronoun, topics=[])

    def delete_bot(self, name):
        c = self.connection.cursor()
        c.execute("delete from bot where name = ?", (name,))
        self.connection.commit()


class BotBot:
    """
    A docstring documenting this bot.
    """

    def __init__(self, db_path="botbot.db"):
        self.db = BotDatabase(db_path)

    def usage(self):
        return "BotBot! The Bot for learning about bots."

    def help(self):
        return """Hi, and thanks for asking!

I'm BotBot, and I'm here to help you find helpful bots. I like to try and figure out what you
mean if you just speak naturally, but really I'm just spotting keywords.

You could say:

"Hey, which bot would be a good example in usage notes?"

or just:

"example"

Ask "Who do you know?" to get a list of bots.
If you know a new bot you could say something like:

"Hi, I absolutely must introduce you to @**Example Bot**, they are all about examples and usage
instructions."

(The syntax is "introduce to <mention name>, <pronoun> about <list of topics>")

Delete a bot with:

"Forget about @**Example Bot**, he doesn't actually exist."

(The syntax is "forget <name>".)
"""

    def who_can(self, words):
        for word in words:
            bot = self.db.lookup_topic(word)
            if bot:
                return self.describe_bot(bot)
        return "Sorry, I don't know how to help you with that."

    def describe_bot(self, bot):
        if bot.pronoun == "I":
            return f"I can help you with that. I know all the best bots."
        return f"My friend {mention(bot.name)} can help you with that. {bot.pronoun.title()} {be[bot.pronoun]} { random.choice(compliments) }."

    def handle_message(self, message, bot_handler):
        logging.info("Received message: %r", message)
        if "-bot@" in message["sender_email"]:
            logging.info("Dropping message from a bot!")
            # Bots don't talk to bots to each other where humans can hear.
            return

        words = stemmed_words(message["content"])
        logging.info(words)
        reply = ""
        if words[0] == "thank":
            reply = random.choice(welcomes)
        elif words[0] == "help":
            reply = self.help()
        elif words[0] == "forget":
            reply = self.handle_forgetfulness(message["content"])
        elif message["content"].lower().startswith("who do you know"):
            bots = make_comma_list([mention(bot.name) for bot in self.db.bots()])
            reply = f"I know everyone: {bots}."
        elif "introduce" in words:
            reply = self.handle_introduction(message["content"])
        else:
            reply = self.who_can(words)

        bot_handler.send_reply(message, reply)

    def handle_introduction(self, content):
        bot = parse_introduction(content)
        if bot:
            new, new_topics = self.db.add_bot(bot)
            if new:
                return f"Thanks! I love meeting new people and can't wait to talk to {accusative(bot.pronoun)}."
            if new_topics:
                return f"Thank you! I already know { bot.name }, but didn't know { bot.pronoun  } knew about {' '.join( new_topics )}."
            return f"Thank you! I already know { bot.name }. They are { random.choice(compliments) }!"
        return "I love to meet new people, but I don't understand."

    def handle_forgetfulness(self, content):
        match = re.search(r"forget.+@(?:\*\*(.+?)\*\*|(\w+))", content, re.IGNORECASE)
        if match:
            name = match.group(1) or match.group(2)
            bot = self.db.lookup_bot(name)
            if bot.pronoun == "I":
                return "I'm unforgettable."
            if bot:
                self.db.delete_bot(name)
                return f"I'll never speak of {name} again."
            return "I'm don't remember if I ever knew them."
        return "Who should I forget?"


class FakeHandler:
    def __init__(self):
        self.replies = []

    def send_reply(self, _message, reply):
        self.replies.append(reply)


def test_add_pairing():
    bot = BotBot(":memory:")
    handler = FakeHandler()
    bot.handle_message(
        {
            "content": "I'd like to introduce you to @**Pairing Bot!**, she knows about pair and pearing",
            "sender_email": "test",
        },
        handler,
    )

    assert handler.replies[0].startswith("Thanks")
    assert bot.db.lookup_topic("pear").name == "Pairing Bot!"
    assert bot.db.lookup_topic("pair").pronoun == "she"


def test_parse_introduction():
    bot = parse_introduction(
        "I'd like to introduce you to @**Pairing Bot!**, she knows about pair and pearing"
    )

    assert bot.name == "Pairing Bot!"
    assert bot.pronoun == "she"
    assert bot.topics == ["pair", "pear"]

    bot = parse_introduction(
        "I'd like to introduce you to @BotBot, you know about bots."
    )

    assert bot.name == "BotBot"
    assert bot.pronoun == "I"
    assert bot.topics == ["bot"]


def test_forget():
    bot = BotBot(":memory:")
    handler = FakeHandler()
    bot.db.add_bot(Bot(name="bad bot", pronoun="he", topics=["swearing", "shouting"]))

    bot.handle_message(
        {"content": "Forget about @**bad bot**!", "sender_email": "test"}, handler
    )
    assert handler.replies[0] == "I'll never speak of bad bot again."
    assert bot.db.lookup_topic("swearing") is None


handler_class = BotBot

common_words = [
    "the",
    "at",
    "there",
    "some",
    "my",
    "of",
    "be",
    "use",
    "her",
    "than",
    "and",
    "this",
    "an",
    "would",
    "first",
    "a",
    "have",
    "each",
    "make",
    "water",
    "to",
    "from",
    "which",
    "like",
    "been",
    "in",
    "or",
    "she",
    "him",
    "call",
    "is",
    "one",
    "do",
    "into",
    "who",
    "you",
    "had",
    "time",
    "oil",
    "that",
    "by",
    "their",
    "has",
    "its",
    "it",
    "word",
    "if",
    "look",
    "now",
    "he",
    "but",
    "will",
    "two",
    "find",
    "was",
    "not",
    "up",
    "more",
    "long",
    "for",
    "what",
    "other",
    "write",
    "down",
    "on",
    "all",
    "about",
    "go",
    "day",
    "are",
    "were",
    "out",
    "see",
    "did",
    "as",
    "we",
    "many",
    "number",
    "get",
    "with",
    "when",
    "then",
    "no",
    "come",
    "his",
    "your",
    "them",
    "way",
    "made",
    "they",
    "can",
    "these",
    "could",
    "may",
    "I",
    "said",
    "so",
    "people",
    "part",
    "rc",
]
