import traceback
import re
import requests


class Slack():
    """Class responsible for all iteractions with Slack, EXCEPT for receiving
    messages (They are received as HTTPS requests from Slack to a webserver,
    which currently feeds them to stdin of this script running with `--talk`
    argument)
    """

    def __init__(self, bot_token, app_token):
        self.bot_token = bot_token
        self.app_token = app_token
        self.my_username = 'cf-bottom'

    def api(self, name):
        return 'https://slack.com/api/' + name

    def post(self, url, data={}):
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

    def set_reply_to(self, message):
        """Saves parameters of original message (channel and username) for
        easy _reply_ function
        """
        self.reply_to_channel = message['channel']
        self.reply_to_user = message['user']

    def reply(self, text, mention=False):
        """Replies to saved channel, optionally mentioning saved user"""
        if mention:
            text = '<@{}>: {}'.format(self.reply_to_user, text)
        self.send_message(self.reply_to_channel, text)


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
        # remove bot username from string
        text = re.sub('<@{}> *:? *'.format(self.slack.my_username), '', text)
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
