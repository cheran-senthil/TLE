# TLE
TLE is a Discord bot centered around Competitive Programming.

## Features
The features of the bot is split into a number of cogs, each handling their own set of commands.

### Codeforces cogs
- **Codeforces** Commands that can recommend problems or contests to users, taking their rating into account.
- **Contests** Shows details of upcoming/running contests.
- **Graphs** Plots various data gathered from Codeforces, e.g. rating distributions and user problem statistics.
- **Handles** Gets or sets information about a specific user's Codeforces handle, or shows list of Codeforces handles.

### CSES cog
- **CSES** Commands related to the [CSES problemset](https://cses.fi/problemset/), such as showing leaderboards.

### Other cogs
- **Starboard** Commands related to the starboard, which adds messages to a specific channel when enough users react with a ⭐️.
- **CacheControl** Commands related to data caching.

## Installation
Clone the repository
```bash
git clone https://github.com/cheran-senthil/TLE
```
Now all dependencies need to be installed. TLE uses [Poetry](https://poetry.eustace.io/) to manage dependencies. After installing Poetry navigate to the root of the repo and run

```bash
poetry install
```

You will need to setup a bot on your server before continuing, follow the directions [here](https://github.com/reactiflux/discord-irc/wiki/Creating-a-discord-bot-&-getting-a-token). Following this you should have your bot appearing in your server and you should have the Discord bot token.

To start TLE export the token as an environment variable
```
export BOT_TOKEN="<BOT_TOKEN_FROM_DISCORD_CONSOLE>"
```
and run using Python 3.7 or later
```
poetry run python -m tle
```

### Notes
 - In order to run admin-only commands you need to have the `Admin` role, which needs to be created in your Discord server and assign it to yourself/other administrators.
 - In order to prevent the bot suggesting an author's problems to the author a python file needs to be run (since this can not be done through the Codeforces API) which will save the authors for specific contests to a file. To do this run `python extra/scrape_cf_contest_writers.py` which will generate a JSON file which should be placed in the `/files` folder. 
 - In order to display CJK (East Asian) characters for usernames, we need appropriate fonts. Their size is ~36MB, so we don't keep in the repo itself and it is gitignored. They will be downloaded automatically when the bot is run if not already present.
 - One of the bot's features is to assign roles to users based on their rating on Codeforces. In order for this functionality to work properly the following roles need to exist in your Discord server
     - Newbie
     - Pupil
     - Specialist
     - Expert
     - Candidate Master
     - Master
     - International Master
     - Grandmaster
     - International Grandmaster
     - Legendary Grandmaster

## Usage
In order to run bot commands you can either ping the bot at the beginning of the command or prefix the command with a semicolon (;), e.g. `;handle pretty`.

In order to find available commands you can run `;help` which will bring a list of commands/groups of commands which are available. To get more details about a specific command you can type `;help <command-name>`.

## Contributing
Pull requests are welcome. For major changes please open an issue first to discuss what you would like to change.

Before submitting your PR, consider running some code formatter on the lines you touched or added. This will help reduce the time spent on fixing small styling issues in code review. Good options are [yapf](https://github.com/google/yapf) or [autopep8](https://github.com/hhatto/autopep8) which likely can be integrated in your favorite editor.

Please refrain from formatting the whole file if you just change some small part of it. If you feel the need to tidy up some particularily egregious code, then do that in a separate PR.

## License
[MIT](https://choosealicense.com/licenses/mit/)
