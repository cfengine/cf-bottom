import traceback
import re
import sys
import json
import requests
import logging as log


class Slack():
    """Class responsible for all iteractions with Slack, EXCEPT for receiving
    messages (They are received as HTTPS requests from Slack to a webserver,
    which currently feeds them to stdin of this script running with `--talk`
    argument)
    """

    reply_to_channel = None
    reply_to_user = None

    def __init__(self, read_token, bot_token, app_token, username, interactive):
        self.read_token = read_token
        self.bot_token = bot_token
        self.app_token = app_token
        self.my_username = username
        self.interactive = interactive

    def api(self, name):
        return 'https://slack.com/api/' + name

    def post(self, url, data={}):
        if os.getenv("TOM") == "PASSIVE":
            print("Would post: " + url)
            return None
        if not url.startswith('http'):
            url = self.api(url)
        if not 'token' in data:
            data['token'] = self.bot_token
        r = requests.post(url, data)
        assert r.status_code >= 200 and r.status_code < 300
        try:
            log.debug(pretty(r.json()))
            return r.json()
        except:
            log.debug(pretty(r.text))
            return False

    def send_message(self, channel, text):
        """Sends a message to a channel"""
        if not channel:
            return
        self.post('chat.postMessage', data={"channel": channel, "text": text})

    def reply(self, text, mention=False):
        """Replies to saved channel, optionally mentioning saved user"""
        if mention:
            text = '<@{}>: {}'.format(self.reply_to_user, text)
        if log.getLogger().getEffectiveLevel() >= log.INFO:
            log.info('SLACK: {}'.format(text))
        elif self.interactive:
            print(text)
        if self.reply_to_channel is not None:
            self.send_message(self.reply_to_channel, text)

    def parse_stdin(self, dispatcher):
        """Reads raw message (in JSON format, as received from Slack servers)
        from stdin, checks it, and calls dispatcher.parse with message text
        """

        message = json.load(sys.stdin)

        log.debug(pretty(message))
        if self.read_token == None:
            log.warning('no read token provided - bluntly trusting incoming message')
        else:
            if 'token' not in message or message['token'] != self.read_token:
                log.warning('Unauthorized message - ignoring')
                return
        if 'authed_users' in message and len(message['authed_users']) > 0:
            self.my_username = message['authed_users'][0]
        message = message['event']
        if not 'user' in message:
            # not a user-generated message
            # probably a bot-generated message
            # TODO: maybe check only for self.my_username here - to allow bots
            # talk to each other?
            log.warning('Not a user message - ignoring')
            return
        self.reply_to_channel = message['channel']
        self.reply_to_user = message['user']
        # remove bot username from string
        text = re.sub('<@{}> *:? *'.format(self.my_username), '', message['text'])
        dispatcher.parse_text(text)


class CommandDispatcher():
    """Class responsible for processing user input (Slack messages) and
    dispatching relevant commands
    """

    def __init__(self, slack):
        self.slack = slack
        self.help_lines = [
            'List of commands bot recognises ' + '(prefix each command with bot name)'
        ]
        self.commands = [{}, {}]
        self.register_command(
            'help', lambda: self.show_help(), False, 'Show this text',
            'Shows overview of all commands')

    def register_command(self, keyword, callback, parameter_name, short_help, long_help=''):
        """Register a command as recognised by Tom.
        Args:
            keyword - text that Tom should react to
            callback - function that should be called when Tom receives a
                message with keyword
            parameter_name - name of parameter for commands with parameter, or
                False for commands without
            short_help - short description of command (Tom prints it in reply
                to `@cf-bottom help` command)
            long_help - long description of command (Tom will print it in reply
                to `@cf-bottom help on <keyword>` command - TODO: implement)
        """
        parameters_count = 1 if parameter_name else 0
        self.commands[parameters_count][keyword] = {'callback': callback, 'long_help': long_help}
        if parameter_name:
            self.help_lines.append(
                '{}: _{}_\n-  {}'.format(keyword, parameter_name.upper(), short_help))
        else:
            self.help_lines.append('{}\n-  {}'.format(keyword, short_help))

    def parse_text(self, text):
        """Analyze user message and react on it - call a registered command"""
        m = re.match(' *([^:]*)(?:[:] *([^ ]*))?', text)
        keyword = m.group(1)
        argument = m.group(2)
        if argument:
            parameters_count = 1
            arguments = [argument]
        else:
            parameters_count = 0
            arguments = []
        if keyword in self.commands[parameters_count]:
            try:
                self.commands[parameters_count][keyword]['callback'](*arguments)
            except:
                self.slack.reply(
                    'I crashed on your command:' + '\n```\n{}\n```'.format(traceback.format_exc()),
                    True)
        else:
            self.slack.reply(("Unknown command. Say \"<@{}> help\" for "+
                "list of known commands")\
                .format(self.slack.my_username))

    def show_help(self):
        """Print basic help info"""
        self.slack.reply('\n\n'.join(self.help_lines))
