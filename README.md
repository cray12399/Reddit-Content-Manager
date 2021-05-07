# Reddit Content Manager

This is a program that uses the [Reddit PushShift API](https://github.com/pushshift/api "Reddit PushShift API") and [Official Reddit API](https://www.reddit.com/dev/api "Official Reddit API") to easily manage a user's Reddit content history as well as migrate and download account data. 

## Setup
**Gaining API access**
This program requires access to the Reddit API in order to function. In order to give your account API access:
1. Navigate to https://www.reddit.com/prefs/apps
2. Log in to your account if you haven't done so already.
3. Press "are you a developer? create an app..."
4. For the name, write "Reddit Content Manager."
5. Select script.
6. Set the about url and redirect url to "https://www.nowebsite.com"
7. Press "create app"
8. You now have API access! Take note of the Personal Use Script and Secret keys (you will need them to give the program access to the API).

**Creating a Reddit Profile:**
This program utilizes profiles in order to keep track of account credentials. A user must create at least one profile before they can use the program. This can be done through:

`Profile -> Create...`

1. Fill out your Account credentials. You will need the personal use script and secret keys that were acquired earlier.
2. After you have correctly filled out your account information, press confirm and the profile manager will verify access to the Reddit API. If it is successful, the profile will be added to the profile directory.

**Note:** If you wish to modify your profile, you can do so though:

``Profile -> Modify...``

If the information is correct, the program will update your local profile.

## Usage

**Searching Content:**

The main function of this program is to manage your Reddit content history (posts and comments). To search your content history:

- To search within the body of posts and comments, you can use the search bar at the top of the screen. If a comment or post contains the exact text written, it will show up in your search results.

- You can toggle between posts and comments through the search filters.

- Use the search filters to search for content with specific attributes.

- Press the search button and the program will automatically gather your content history through the [Reddit PushShift API](https://github.com/pushshift/api "Reddit PushShift API") and the [Official Reddit API](https://www.reddit.com/dev/api "Official Reddit API")

**Viewing Content:**

If the program found any content, it will be displayed in the results widget in the middle of the screen.

- Content is organized based on the sort filter. (New -> Old | Top Score -> Lowest Score)
- Content is displayed by ID and Creation Date. You can display more information by using the drop down arrow to the left of the ID.
- If a content ID is red, then that means it represents deleted content.
- You can view your comment on Reddit by double clicking the hyperlink displayed under the ID (if the content is deleted, it will not be displayed on your browser).
- Content can be cleared using the Clear button below.

**Deleting Content:**

You can delete content by clicking the ID(s) of the content you wish to delete and pressing the delete button below.

**Note:** Due to API limitations, this can process can take a long time to complete depending on the amount of content that is selected.


**Dumping Content:**

Your Reddit content can be dumped to a CSV, JSON, or CSV file by selecting the content you wish to save and selecting the Dump button below.

**Migrating Subs:**

If you wish to migrate your Subreddit subscriptions, you can do so using the Migrate Subs button in the profile directory.

1. Select the profile from which you wish to migrate your subscriptions.
2. Select a second profile to which you wish to migrate your subscriptions.
3. Press the Migrate Subs button and wait for the program to complete the process. Be aware that it may take several minutes depending on the subscription count.
