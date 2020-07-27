import sys
from collections import OrderedDict
from PySide2.QtWidgets import *
from PySide2.QtCore import *
from PySide2.QtGui import *
from mainwindow import UIMainWindow
from profilewindow import UIProfileWindow
import os
import praw
import datetime
import shutil
import requests
import json
import textwrap
import webbrowser
import pandas

log_file = f"logs/{datetime.datetime.now().strftime('%m%d%Y - %H%M%S')}.log"


class ThreadDeleteContent(QThread):
    remove_comment = Signal(int)
    thread_progress = Signal(int)
    thread_status = Signal(str)

    def __init__(self, parent, profile):
        self.stopped = False
        self.parent = parent
        self.profile = profile

        super().__init__()

    def run(self):
        try:
            reddit = praw.Reddit(username=self.profile[0],
                                 password=self.profile[1],
                                 client_id=self.profile[2],
                                 client_secret=self.profile[3],
                                 user_agent="Reddit Content Manager")
            reddit.validate_on_submit = True

        except Exception as e:
            if not self.stopped:
                log(e)
                self.thread_status.emit("Process ran into error. Please try again in a few minutes...")
            return

        content_deleted = 0
        content_already_deleted = 0
        total_to_delete = len(self.parent.ui.content_tree.selectedItems())
        for index, item in enumerate(reversed(self.parent.ui.content_tree.selectedItems())):
            if self.stopped:
                self.thread_status.emit("Process stopped by user...")
                return

            if item.statusTip(0) == "Reddit Content":
                if self.parent.current_search == "comments":
                    try:
                        reddit.comment(item.text(0)).edit("[removed]")
                        reddit.comment(item.text(0)).delete()
                        content_deleted += 1
                        item.setSelected(False)
                        item.setTextColor(0, QColor(255, 0, 0))
                    except Exception as e:
                        log(e)
                else:
                    try:
                        try:
                            reddit.submission(item.text(0)).edit("[removed]")
                            # Tries to edit the text, if it can't (because it isn't a text post), then it just catches
                            # the exception and passes it.
                        except:
                            pass
                        reddit.submission(item.text(0)).delete()
                        content_deleted += 1
                        item.setSelected(False)
                        item.setTextColor(0, QColor(255, 0, 0))
                    except Exception as e:
                        log(e)
            else:
                content_already_deleted += 1
                item.setSelected(False)

            self.thread_status.emit(f"Deleting content ({index}/{total_to_delete})")
            self.thread_progress.emit((index / total_to_delete) * 100)

        self.thread_status.emit(f"Done! {content_deleted} removed. | {content_already_deleted} already removed.")

    def stop_thread(self):
        self.stopped = True


class ThreadGatherPosts(QThread):
    output_post = Signal(list)
    thread_progress = Signal(int)
    thread_status = Signal(str)

    def __init__(self, parent, profile, search_text, filters):
        try:
            self.stopped = False
            self.parent = parent
            self.profile = profile
            self.search_text = search_text
            self.filters = filters

            super().__init__()

            log("Background thread started!")
        except Exception as e:
            log(e)

    def run(self):
        posts = self.get_post_info()
        posts = self.filter_posts(posts)
        self.output_posts(posts)

        num_found = len([post for post in posts.keys() if posts[post]["drop"] is not True])
        self.thread_status.emit(f"Process finished! {num_found} posts found!")
        self.parent.current_profile = self.parent.ui.profile_list.selectedItems()[0].text()
        log("Thread execution finished successfully!")

    def get_post_info(self):
        log("Getting posts...")
        self.thread_status.emit("Getting posts...")

        push_link = f"https://api.pushshift.io/reddit/search/submission/?q={self.search_text}" \
                    f"&sort_type=created_utc" \
                    f"&author={self.profile[0]}" \
                    f"&{['after', 'before'][self.filters['Time'][0]]}={self.filters['Time'][1]}" \
                    f"&limit=1000"

        try:
            posts = json.loads(requests.get(push_link).content)
        except Exception as e:
            if not self.stopped:
                log(e)
                self.thread_status.emit("Process ran into error. Please try again in a few minutes...")
            return

        if not posts["data"]:
            self.thread_status.emit("No results found...")
            raise Exception("No results found...")

        while len(json.loads(requests.get(push_link).content)["data"]) != 0:
            if self.stopped:
                self.thread_status.emit("Process stopped by user...")
                return

            try:
                push_link = f"https://api.pushshift.io/reddit/search/submission/?q={self.search_text}" \
                            f"&sort_type=created_utc" \
                            f"&author={self.profile[0]}" \
                            f"&{['after', 'before'][self.filters['Time'][0]]}={posts['data'][-1]['created_utc']}" \
                            f"&subreddit={self.filters['Subreddit']}" \
                            f"&limit=1000"

                posts["data"] = posts["data"] + json.loads(requests.get(push_link).content)["data"]
            except Exception as e:
                if not self.stopped:
                    log(e)
                    self.thread_status.emit("Process ran into error. Please try again in a few minutes...")
                return

        try:
            reddit = praw.Reddit(username=self.profile[0],
                                 password=self.profile[1],
                                 client_id=self.profile[2],
                                 client_secret=self.profile[3],
                                 user_agent="Reddit Content Manager")
        except Exception as e:
            if not self.stopped:
                log(e)
                self.thread_status.emit("Process ran into error. Please try again in a few minutes...")
            return

        posts_by_id = OrderedDict({post["id"]: {"selftext": post["selftext"],
                                                "title": post["title"],
                                                "subreddit": post["subreddit"],
                                                "permalink": post["permalink"],
                                                "created": post["created_utc"],
                                                "score": "Unknown",
                                                "edited": "Unknown",
                                                "awarded": "Unknown",
                                                "removed": "Unknown",
                                                "processed": False,  # used to determine if the content was processed
                                                "drop": False  # used to determine if content matches filters or not
                                                } for post in posts["data"]})
        post_ids = list(posts_by_id.keys())

        log("Getting post info...")
        self.thread_status.emit(f"Getting post info... (0/{len(post_ids)})")

        try:
            if len(post_ids) >= 100:
                for iteration in range(100, len(post_ids), 100):
                    if self.stopped:
                        self.thread_status.emit("Process stopped by user...")
                        return

                    current_posts = ["t3_" + post_id for post_id in post_ids[iteration - 100:iteration]]
                    current_post_info = [post_info for post_info in reddit.info(current_posts)]
                    post_score_info = {post.id: post.score for post in current_post_info}
                    post_awarded_info = {post_info.id: post_info.distinguished is not None for post_info in
                                         current_post_info}
                    post_edited_info = {post_info.id: post_info.edited is not False for post_info in
                                        current_post_info}
                    post_removed_info = {post_info.id: post_info.selftext in ["[removed]", "[deleted]"] for
                                         post_info in current_post_info}
                    post_selftext_info = {post_info.id: post_info.selftext for post_info in current_post_info}

                    for post_id in post_ids[iteration - 100:iteration]:
                        if post_id in post_score_info.keys():
                            posts_by_id[post_id]["score"] = post_score_info[post_id]
                        if post_id in post_awarded_info.keys():
                            posts_by_id[post_id]["awarded"] = post_awarded_info[post_id]
                        if post_id in post_edited_info.keys():
                            posts_by_id[post_id]["edited"] = post_edited_info[post_id]
                        if post_id in post_removed_info.keys():
                            posts_by_id[post_id]["removed"] = post_removed_info[post_id]
                        if post_id in post_selftext_info.keys():
                            if post_selftext_info[post_id] not in ["[removed]", "[deleted]"]:
                                posts_by_id[post_id]["selftext"] = post_selftext_info[post_id]

                        posts_by_id[post_id]["processed"] = True

                    num_complete = len([post_id for post_id in post_ids
                                        if posts_by_id[post_id]["processed"] is True])

                    self.thread_status.emit(f"Getting post info... ({num_complete}/{len(post_ids)})")
                    self.thread_progress.emit((num_complete / len(post_ids) * 100))

            if self.stopped:
                self.thread_status.emit("Process stopped by user...")
                return

            # Code below exists to process remainders or content that falls below the 100 item limit for .info
            current_posts = ["t3_" + post_id for post_id in post_ids
                             if posts_by_id[post_id]["processed"] is False]
            current_post_info = [post_info for post_info in reddit.info(current_posts)]
            post_score_info = {post_info.id: post_info.score for post_info in current_post_info}
            post_awarded_info = {post_info.id: post_info.distinguished for post_info in
                                 current_post_info}
            post_edited_info = {post_info.id: post_info.edited is not False for post_info in
                                current_post_info}
            post_removed_info = {post_info.id: post_info.selftext in ["[removed]", "[deleted]"] for
                                 post_info in current_post_info}
            post_selftext_info = {post_info.id: post_info.selftext for post_info in current_post_info}

            for post_id in current_posts:
                post_id = post_id.replace("t3_", "")

                if post_id in post_score_info.keys():
                    posts_by_id[post_id]["score"] = post_score_info[post_id]
                if post_id in post_awarded_info.keys():
                    posts_by_id[post_id]["awarded"] = post_awarded_info[post_id]
                if post_id in post_edited_info.keys():
                    posts_by_id[post_id]["edited"] = post_edited_info[post_id]
                if post_id in post_removed_info.keys():
                    posts_by_id[post_id]["removed"] = post_removed_info[post_id]
                if post_id in post_selftext_info.keys():
                    if post_selftext_info[post_id] not in ["[removed]", "[deleted]"]:
                        posts_by_id[post_id]["body"] = post_selftext_info[post_id]

                posts_by_id[post_id]["processed"] = True

            num_complete = len([post_id for post_id in post_ids
                                if posts_by_id[post_id]["processed"] is True])

            self.thread_status.emit(f"Getting post info... ({num_complete}/{len(post_ids)})")
            self.thread_progress.emit((num_complete / len(post_ids) * 100))

            log("Done getting post info!")
        except Exception as e:
            if not self.stopped:
                log(e)
                self.thread_status.emit("Process ran into error. Please try again in a few minutes...")
            return

        return posts_by_id

    def filter_posts(self, posts):
        if self.stopped:
            self.thread_status.emit("Process stopped by user...")
            return

        try:
            log("Filtering posts...")
            self.thread_status.emit(f"Filtering posts... (0/{len(posts)})")

            for index, post_id in enumerate(posts):
                score = posts[post_id]["score"]
                awarded = posts[post_id]["awarded"]
                edited = posts[post_id]["edited"]
                removed = posts[post_id]["removed"]

                if score != "Unknown":
                    if score < self.filters["Score"][0] or score > self.filters["Score"][1]:
                        posts[post_id]["drop"] = True

                if awarded != "Unknown":
                    if self.filters["Awarded"] != 0:
                        if self.filters["Awarded"] == 1:
                            posts[post_id]["drop"] = not awarded
                        else:
                            posts[post_id]["drop"] = bool(awarded)
                else:
                    if self.filters["Awarded"] != 0:
                        posts[post_id]["drop"] = True

                if edited != "Unknown":
                    if self.filters["Edited"] != 0:
                        if self.filters["Edited"] == 1:
                            posts[post_id]["drop"] = True if edited is False else False
                        else:
                            posts[post_id]["drop"] = True if edited is not False else False
                else:
                    if self.filters["Edited"] != 0:
                        posts[post_id]["drop"] = True

                if removed != "Unknown":
                    if self.filters["Removed"] != 0:
                        if self.filters["Removed"] == 1:
                            posts[post_id]["drop"] = True if removed is False else False
                        else:
                            posts[post_id]["drop"] = True if removed is not False else False

                self.thread_status.emit(f"Filtering posts... ({index}/{len(posts) - 1})")
                self.thread_progress.emit((index / len(posts) * 100))

            if self.filters["Sort"] == 0:
                posts = OrderedDict((sorted((kv for kv in posts.items()), key=lambda kv: kv[1]['created'],
                                            reverse=True)))
            else:
                posts_score_unknown = OrderedDict(kv for kv in posts.items() if kv[1]['score'] == "Unknown")
                posts = OrderedDict(kv for kv in posts.items() if kv[1]['score'] != "Unknown")
                posts = OrderedDict((sorted((kv for kv in posts.items()), key=lambda kv: kv[1]['score'],
                                            reverse=True)))
                posts = OrderedDict([kv for kv in posts.items()] + [kv for kv in posts_score_unknown.items()])

            log("Done filtering posts!")
        except Exception as e:
            if not self.stopped:
                log(e)
                self.thread_status.emit("Process ran into error. Please try again in a few minutes...")
            return

        return posts

    def output_posts(self, posts):
        if self.stopped:
            self.thread_status.emit("Process stopped by user...")
            return

        log("Outputting posts...")
        self.thread_status.emit(f"Outputting comments... (0/{len(posts)})")

        try:
            for index, post_id in enumerate(posts):
                if self.stopped:
                    self.thread_status.emit("Process stopped by user...")
                    return

                if posts[post_id]["drop"] is False:
                    self.output_post.emit({"index": index, "id": post_id,
                                           "data": posts[post_id], "num_comments": len(posts)})

                self.thread_status.emit(f"Outputting posts... ({index}/{len(posts) - 1})")
                self.thread_progress.emit(index / len(posts) * 100)

            log("Done outputting posts!")
        except Exception as e:
            if not self.stopped:
                log(e)
                self.thread_status.emit("Process ran into error. Please try again in a few minutes...")
            return

    def stop_thread(self):
        self.stopped = True


class ThreadGatherComments(QThread):
    output_comment = Signal(list)
    thread_progress = Signal(int)
    thread_status = Signal(str)

    def __init__(self, parent, profile, search_text, filters):
        try:
            self.stopped = False
            self.parent = parent
            self.profile = profile
            self.search_text = search_text
            self.filters = filters

            super().__init__()

            log("Background thread started!")
        except Exception as e:
            log(e)

    def run(self):
        comments = self.get_comment_info()
        comments = self.filter_comments(comments)
        self.output_comments(comments)

        if self.stopped:
            return

        num_found = len([comment for comment in comments.keys() if comments[comment]["drop"] is not True])
        self.thread_status.emit(f"Process finished! {num_found} comments found!")
        self.parent.current_profile = self.parent.ui.profile_list.selectedItems()[0].text()
        log("Thread execution finished successfully!")

    def get_comment_info(self):
        log("Getting comments...")
        self.thread_status.emit("Getting comments...")

        push_link = f"https://api.pushshift.io/reddit/search/comment/?q={self.search_text}" \
                    f"&sort_type=created_utc" \
                    f"&author={self.profile[0]}" \
                    f"&{['after', 'before'][self.filters['Time'][0]]}={self.filters['Time'][1]}" \
                    f"&limit=1000"

        try:
            comments = json.loads(requests.get(push_link).content)
        except Exception as e:
            if not self.stopped:
                log(e)
                self.thread_status.emit("Process ran into error. Please try again in a few minutes...")
            return

        if not comments["data"]:
            self.thread_status.emit("No results found...")
            raise Exception("No results found...")

        while 1:
            if self.stopped:
                self.thread_status.emit("Process stopped by user...")
                return

            try:
                push_link = f"https://api.pushshift.io/reddit/search/comment/?q={self.search_text}" \
                            f"&sort_type=created_utc" \
                            f"&author={self.profile[0]}" \
                            f"&{['after', 'before'][self.filters['Time'][0]]}={comments['data'][-1]['created_utc']}" \
                            f"&subreddit={self.filters['Subreddit']}" \
                            f"&limit=1000"

                comments["data"] = comments["data"] + json.loads(requests.get(push_link).content)["data"]

                if len(json.loads(requests.get(push_link).content)["data"]) == 0:
                    break
            except Exception as e:
                if not self.stopped:
                    log(e)
                    self.thread_status.emit("Process ran into error. Please try again in a few minutes...")
                return

        try:
            reddit = praw.Reddit(username=self.profile[0],
                                 password=self.profile[1],
                                 client_id=self.profile[2],
                                 client_secret=self.profile[3],
                                 user_agent="Reddit Content Manager")
        except Exception as e:
            if not self.stopped:
                log(e)
                self.thread_status.emit("Process ran into error. Please try again in a few minutes...")
            return

        comments_by_id = OrderedDict({comment["id"]: {"body": comment["body"],
                                                      "subreddit": comment["subreddit"],
                                                      "permalink": comment["permalink"],
                                                      "created": comment["created_utc"],
                                                      "score": "Unknown",
                                                      "edited": "Unknown",
                                                      "awarded": "Unknown",
                                                      "removed": "Unknown",
                                                      "processed": False,
                                                      "drop": False
                                                      } for comment in comments["data"]})

        for comment in reddit.redditor(self.profile[0]).comments.new(limit=None):
            if comment.id not in comments_by_id.keys():
                comments_by_id[comment.id] = {"body": comment.body,
                                              "subreddit": comment.subreddit,
                                              "permalink": comment.permalink,
                                              "created": comment.created_utc,
                                              "score": "Unknown",
                                              "edited": "Unknown",
                                              "awarded": "Unknown",
                                              "removed": "Unknown",
                                              "processed": False,
                                              "drop": False}

        comment_ids = list(comments_by_id.keys())

        log("Getting comment info...")
        self.thread_status.emit(f"Getting comment info... (0/{len(comment_ids)})")

        try:
            if len(comment_ids) >= 100:
                for iteration in range(100, len(comment_ids), 100):
                    if self.stopped:
                        self.thread_status.emit("Process stopped by user...")
                        return

                    current_comments = ["t1_" + comment_id for comment_id in comment_ids[iteration - 100:iteration]]
                    current_comment_info = [comment_info for comment_info in reddit.info(current_comments)]

                    comment_score_info = {comment.id: comment.score for comment in current_comment_info}
                    comment_awarded_info = {comment_info.id: comment_info.distinguished is not None for comment_info in
                                            current_comment_info}
                    comment_edited_info = {comment_info.id: comment_info.edited is not False for comment_info in
                                           current_comment_info}
                    comment_removed_info = {comment_info.id: comment_info.body in ["[removed]", "[deleted]"] for
                                            comment_info in current_comment_info}
                    comment_body_info = {comment_info.id: comment_info.body for comment_info in current_comment_info}

                    for comment_id in comment_ids[iteration - 100:iteration]:
                        if comment_id in comment_score_info.keys():
                            comments_by_id[comment_id]["score"] = comment_score_info[comment_id]
                        if comment_id in comment_awarded_info.keys():
                            comments_by_id[comment_id]["awarded"] = comment_awarded_info[comment_id]
                        if comment_id in comment_edited_info.keys():
                            comments_by_id[comment_id]["edited"] = comment_edited_info[comment_id]
                        if comment_id in comment_removed_info.keys():
                            comments_by_id[comment_id]["removed"] = comment_removed_info[comment_id]
                        if comment_id in comment_body_info.keys():
                            if comment_body_info[comment_id] not in ["[removed]", "[deleted]"]:
                                comments_by_id[comment_id]["body"] = comment_body_info[comment_id]

                        comments_by_id[comment_id]["processed"] = True

                    num_complete = len([comment_id for comment_id in comment_ids
                                        if comments_by_id[comment_id]["processed"] is True])
                    self.thread_status.emit(f"Getting comment info... ({num_complete}/{len(comment_ids)})")
                    self.thread_progress.emit((num_complete / len(comment_ids) * 100))

            if self.stopped:
                self.thread_status.emit("Process stopped by user...")
                return

            current_comments = ["t1_" + comment_id for comment_id in comment_ids
                                if comments_by_id[comment_id]["processed"] is False]
            current_comment_info = [comment_info for comment_info in reddit.info(current_comments)]
            comment_score_info = {comment.id: comment.score for comment in current_comment_info}
            comment_awarded_info = {comment_info.id: comment_info.distinguished for comment_info in
                                    current_comment_info}
            comment_edited_info = {comment_info.id: comment_info.edited is not False for comment_info in
                                   current_comment_info}
            comment_removed_info = {comment_info.id: comment_info.body in ["[removed]", "[deleted]"] for
                                    comment_info in current_comment_info}
            comment_body_info = {comment_info.id: comment_info.body for comment_info in current_comment_info}

            for comment_id in current_comments:
                comment_id = comment_id.replace("t1_", "")

                if comment_id in comment_score_info.keys():
                    comments_by_id[comment_id]["score"] = comment_score_info[comment_id]
                if comment_id in comment_awarded_info.keys():
                    comments_by_id[comment_id]["awarded"] = comment_awarded_info[comment_id]
                if comment_id in comment_edited_info.keys():
                    comments_by_id[comment_id]["edited"] = comment_edited_info[comment_id]
                if comment_id in comment_removed_info.keys():
                    comments_by_id[comment_id]["removed"] = comment_removed_info[comment_id]
                if comment_id in comment_body_info.keys():
                    if comment_body_info[comment_id] not in ["[removed]", "[deleted]"]:
                        comments_by_id[comment_id]["body"] = comment_body_info[comment_id]

                comments_by_id[comment_id]["processed"] = True

            num_complete = len([comment_id for comment_id in comment_ids
                                if comments_by_id[comment_id]["processed"] is True])
            self.thread_status.emit(f"Getting comment info... ({num_complete}/{len(comment_ids)})")
            self.thread_progress.emit((num_complete / len(comment_ids) * 100))

            log("Done getting comment info!")
        except Exception as e:
            if not self.stopped:
                log(e)
                self.thread_status.emit("Process ran into error. Please try again in a few minutes...")
            return

        return comments_by_id

    def filter_comments(self, comments):
        if self.stopped:
            self.thread_status.emit("Process stopped by user...")
            return

        try:
            log("Filtering comments...")
            self.thread_status.emit(f"Filtering comments... (0/{len(comments)})")

            for index, comment_id in enumerate(comments):
                score = comments[comment_id]["score"]
                awarded = comments[comment_id]["awarded"]
                edited = comments[comment_id]["edited"]
                removed = comments[comment_id]["removed"]

                if score != "Unknown":
                    if score < self.filters["Score"][0] or score > self.filters["Score"][1]:
                        comments[comment_id]["drop"] = True

                if awarded != "Unknown":
                    if self.filters["Awarded"] != 0:
                        if self.filters["Awarded"] == 1:
                            comments[comment_id]["drop"] = not awarded
                        else:
                            comments[comment_id]["drop"] = bool(awarded)
                else:
                    if self.filters["Awarded"] != 0:
                        comments[comment_id]["drop"] = True

                if edited != "Unknown":
                    if self.filters["Edited"] != 0:
                        if self.filters["Edited"] == 1:
                            comments[comment_id]["drop"] = True if edited is False else False
                        else:
                            comments[comment_id]["drop"] = True if edited is not False else False
                else:
                    if self.filters["Edited"] != 0:
                        comments[comment_id]["drop"] = True

                if removed != "Unknown":
                    if self.filters["Removed"] != 0:
                        if self.filters["Removed"] == 1:
                            comments[comment_id]["drop"] = True if removed is False else False
                        else:
                            comments[comment_id]["drop"] = True if removed is not False else False

                self.thread_status.emit(f"Filtering comments... ({index}/{len(comments) - 1})")
                self.thread_progress.emit((index / len(comments) * 100))

            if self.filters["Sort"] == 0:
                comments = OrderedDict((sorted((kv for kv in comments.items()), key=lambda kv: kv[1]['created'],
                                               reverse=True)))
            else:
                comments_score_unknown = OrderedDict(kv for kv in comments.items() if kv[1]['score'] == "Unknown")
                comments = OrderedDict(kv for kv in comments.items() if kv[1]['score'] != "Unknown")
                comments = OrderedDict((sorted((kv for kv in comments.items()), key=lambda kv: kv[1]['score'],
                                               reverse=True)))
                comments = OrderedDict([kv for kv in comments.items()] + [kv for kv in comments_score_unknown.items()])

            log("Done filtering comments!")
        except Exception as e:
            if not self.stopped:
                log(e)
                self.thread_status.emit("Process ran into error. Please try again in a few minutes...")
            return

        return comments

    def output_comments(self, comments):
        if self.stopped:
            self.thread_status.emit("Process stopped by user...")
            return

        log("Outputting comments...")
        self.thread_status.emit(f"Outputting comments... (0/{len(comments)})")

        try:
            for index, comment_id in enumerate(comments):
                if self.stopped:
                    self.thread_status.emit("Process stopped by user...")
                    return

                if comments[comment_id]["drop"] is False:
                    self.output_comment.emit({"index": index, "id": comment_id,
                                              "data": comments[comment_id], "num_comments": len(comments)})

                self.thread_status.emit(f"Outputting comments... ({index}/{len(comments) - 1})")
                self.thread_progress.emit(index / len(comments) * 100)

            log("Done outputting comments!")
        except Exception as e:
            if not self.stopped:
                log(e)
                self.thread_status.emit("Process ran into error. Please try again in a few minutes...")
            return

    def stop_thread(self):
        self.stopped = True


class ProfileWindow(QDialog):
    def __init__(self, parent, create_profile):
        self.parent = parent

        log("Setting up profile menu UI...")

        try:
            super(ProfileWindow, self).__init__()
            self.ui = UIProfileWindow()
            self.ui.setupUi(self)

            log("Profile menu UI set up successfully!")
        except Exception as e:
            log(e)

        log("Setting up menu...")

        try:
            if create_profile:
                self.ui.confirm_btn.clicked.connect(self.do_create_profile)
                self.setWindowTitle("Create Profile")
            else:
                self.setWindowTitle("Modify Profile")

                with open(f"profiles/{parent.ui.profile_list.selectedItems()[0].text()}.rpf") as file:
                    profile_info = [line.replace("\n", "") for line in file.readlines()]

                if len(profile_info) < 4:
                    profile_info = profile_info + ["" for i in range(4 - len(profile_info))]

                self.ui.username_edit.setText(profile_info[0])
                self.ui.password_edit.setText(profile_info[1])
                self.ui.pu_edit.setText(profile_info[2])
                self.ui.secret_edit.setText(profile_info[3])

                self.ui.confirm_btn.clicked.connect(self.do_modify_profile)

            log("Menu set up successfully!")
        except Exception as e:
            log(e)

        if not os.path.isdir("profiles"):
            log("Creating profile directory...")

            try:
                os.mkdir("profiles")
            except Exception as e:
                log(e)

        log("Profile menu opened successfully!")

    def do_create_profile(self):
        do_create = True

        if len(self.ui.username_edit.text()) == 0:
            do_create = False
            self.ui.username_edit.setStyleSheet("border: 1px solid red;")
        else:
            self.ui.username_edit.setStyleSheet("border: 1px solid black;")

        if len(self.ui.password_edit.text()) == 0:
            do_create = False
            self.ui.password_edit.setStyleSheet("border: 1px solid red;")
        else:
            self.ui.password_edit.setStyleSheet("border: 1px solid black;")

        if len(self.ui.pu_edit.text()) < 14:
            do_create = False
            self.ui.pu_edit.setStyleSheet("border: 1px solid red;")
        else:
            self.ui.pu_edit.setStyleSheet("border: 1px solid black;")

        if len(self.ui.secret_edit.text()) < 27:
            do_create = False
            self.ui.secret_edit.setStyleSheet("border: 1px solid red;")
        else:
            self.ui.secret_edit.setStyleSheet("border: 1px solid black;")

        for user_file in os.listdir("profiles"):
            if self.ui.username_edit.text() == user_file.split(".")[0]:
                do_create = False
                QMessageBox.warning(self, "Profile already exists", "A profile already exists for that user!")

        if do_create == True:
            log("Creating profile...")

            try:
                bot = praw.Reddit(username=self.ui.username_edit.text(),
                                  password=self.ui.password_edit.text(),
                                  client_id=self.ui.pu_edit.text(),
                                  client_secret=self.ui.secret_edit.text(),
                                  user_agent='Reddit Content Manager')

                _ = bot.user.me()  # Verifies connection to Reddit. If not, an exception is raised.

                with open(f"profiles/{self.ui.username_edit.text()}.rpf", "w+") as file:
                    file.writelines([self.ui.username_edit.text() + "\n",
                                     self.ui.password_edit.text() + "\n",
                                     self.ui.pu_edit.text() + "\n",
                                     self.ui.secret_edit.text() + "\n"])

                log("Profile created successfully!")

                self.close()

            except Exception as e:
                if "invalid_grant error processing request" in str(e):
                    QMessageBox.warning(self, "Invalid Login!", "Invalid Username or Password! Please try again!")
                elif "error with request HTTPSConnectionPool" in str(e):
                    QMessageBox.warning(self, "Status Code: 503", "Cannot establish connection!")
                elif "received 401 HTTP response" in str(e):
                    QMessageBox.warning(self, "Status Code: 401", "Invalid PU Script or Secret! Please try again!")
                else:
                    QMessageBox.warning(self, "Unknown Error", "Unknown error! Please check the log for more details!")

                log(e)

    def do_modify_profile(self):
        do_modify = True

        if len(self.ui.username_edit.text()) == 0:
            do_modify = False
            self.ui.username_edit.setStyleSheet("border: 1px solid red;")
        else:
            self.ui.username_edit.setStyleSheet("border: 1px solid black;")

        if len(self.ui.password_edit.text()) == 0:
            do_modify = False
            self.ui.password_edit.setStyleSheet("border: 1px solid red;")
        else:
            self.ui.password_edit.setStyleSheet("border: 1px solid black;")

        if len(self.ui.pu_edit.text()) < 14:
            do_modify = False
            self.ui.pu_edit.setStyleSheet("border: 1px solid red;")
        else:
            self.ui.pu_edit.setStyleSheet("border: 1px solid black;")

        if len(self.ui.secret_edit.text()) < 27:
            do_modify = False
            self.ui.secret_edit.setStyleSheet("border: 1px solid red;")
        else:
            self.ui.secret_edit.setStyleSheet("border: 1px solid black;")

        if do_modify == True:
            log("Modifying profile...")

            try:
                bot = praw.Reddit(username=self.ui.username_edit.text(),
                                  password=self.ui.password_edit.text(),
                                  client_id=self.ui.pu_edit.text(),
                                  client_secret=self.ui.secret_edit.text(),
                                  user_agent='Reddit Content Manager')

                _ = bot.user.me()

                os.remove(f"profiles/{self.parent.ui.profile_list.selectedItems()[0].text()}.rpf")

                with open(f"profiles/{self.ui.username_edit.text()}.rpf", "w+") as file:
                    file.writelines([self.ui.username_edit.text() + "\n",
                                     self.ui.password_edit.text() + "\n",
                                     self.ui.pu_edit.text() + "\n",
                                     self.ui.secret_edit.text() + "\n"])

                log("Profile modified successfully!")

                self.close()

            except Exception as e:
                if "invalid_grant error processing request" in str(e):
                    QMessageBox.warning(self, "Invalid Login!", "Invalid Username or Password! Please try again!")
                elif "error with request HTTPSConnectionPool" in str(e):
                    QMessageBox.warning(self, "Status Code: 503", "Cannot establish connection!")
                elif "received 401 HTTP response" in str(e):
                    QMessageBox.warning(self, "Status Code: 401", "Invalid PU Script or Secret! Please try again!")
                else:
                    QMessageBox.warning(self, "Unknown Error", "Unknown error! Please check the log for more details!")

                log(e)


class MainWindow(QMainWindow):
    def __init__(self):
        super(MainWindow, self).__init__()

        log("Setting up UI...")

        self.prev_max = 0
        self.current_process = None

        try:
            self.ui = UIMainWindow()
            self.ui.setupUi(self)

            log("UI Set up successfully!")
        except Exception as e:
            log(e)

        log("Starting timer...")

        self.ui.content_tree.itemDoubleClicked.connect(self.open_link)

        try:
            self.update_timer = QTimer(self)
            self.connect_functions()
            self.update_timer.start(100)
            log("Timer Started!")
        except Exception as e:
            log(e)

    def updater(self):
        # This is a function that runs on an interval and continuously updates the UI
        profiles = []

        for profile_index in range(self.ui.profile_list.count()):
            profiles.append(self.ui.profile_list.item(profile_index))

        for rpf_file in os.listdir("profiles"):
            if rpf_file.split(".")[0] not in [profile.text() for profile in profiles]:
                self.ui.profile_list.addItem(rpf_file.split(".")[0])

        for profile in profiles:
            if (profile.text() + ".rpf") not in os.listdir("profiles"):
                if (profile.text() + ".txt") not in os.listdir("profiles"):
                    self.ui.profile_list.takeItem(self.ui.profile_list.row(profile))

        self.ui.modify_profile_action.setDisabled(len(self.ui.profile_list.selectedItems()) == 0)
        self.ui.export_profile_action.setDisabled(len(self.ui.profile_list.selectedItems()) == 0)

        self.ui.remove_profile_button.setDisabled(len(self.ui.profile_list.selectedItems()) == 0)
        self.ui.migrate_profile_button.setDisabled(not len(self.ui.profile_list.selectedItems()) == 2)

        self.ui.submission_search_button.setDisabled(not len(self.ui.profile_list.selectedItems()) == 1)
        self.ui.submission_dump_button.setDisabled(not len(self.ui.content_tree.selectedItems()))
        self.ui.submission_delete_button.setDisabled(not len(self.ui.content_tree.selectedItems()))
        self.ui.submission_clear_btn.setDisabled(not len(self.ui.content_tree.selectedItems()))

        try:
            layouts = [self.ui.profile_layout, self.ui.filter_layout]
            for layout in layouts:
                layout_widgets = [layout.itemAt(i) for i in range(layout.count())]
                for widget in layout_widgets:
                    if widget.widget() is not None:
                        widget.widget().setDisabled(self.background_thread.isRunning())

                if isinstance(widget, QCheckBox):
                    widget.setDisabled(self.background_thread.isRunning())

            if not self.background_thread.isRunning():
                self.ui.submission_progress_bar.setValue(0)

            self.ui.content_tree.setDisabled(self.background_thread.isRunning())

            self.ui.submission_label.setDisabled(self.background_thread.isRunning())
            self.ui.submission_search_bar.setDisabled(self.background_thread.isRunning())
            self.ui.profile_menu.setDisabled(self.background_thread.isRunning())
            self.ui.autodelete_menu.setDisabled(self.background_thread.isRunning())

            if self.background_thread.isRunning() and self.current_process == "Search":
                self.ui.submission_search_button.setText("Cancel")
                self.ui.submission_search_button.clicked.disconnect()
                self.ui.submission_search_button.clicked.connect(lambda: self.background_thread.stop_thread())

                self.ui.submission_dump_button.setDisabled(True)
                self.ui.submission_delete_button.setDisabled(True)
                self.ui.submission_clear_btn.setDisabled(True)
            elif self.background_thread.isRunning() and self.current_process == "Delete":
                self.ui.submission_delete_button.setText("Cancel")
                self.ui.submission_delete_button.clicked.disconnect()
                self.ui.submission_delete_button.clicked.connect(lambda: self.background_thread.stop_thread())

                self.ui.submission_search_button.setDisabled(True)
                self.ui.submission_dump_button.setDisabled(True)
                self.ui.submission_clear_btn.setDisabled(True)
            else:
                self.current_process = None

                self.ui.submission_search_button.setText("Search")
                self.ui.submission_search_button.clicked.disconnect()
                self.ui.submission_search_button.clicked.connect(self.search_content)

                self.ui.submission_delete_button.setText("Delete")
                self.ui.submission_delete_button.clicked.disconnect()
                self.ui.submission_delete_button.clicked.connect(self.delete_content)
        except:
            pass

    def connect_functions(self):
        # Connects all of the UI elements to functions at startup
        log("Connecting functions...")
        try:
            self.ui.create_profile_action.triggered.connect(lambda: self.create_modify_profile(True))
            self.ui.modify_profile_action.triggered.connect(lambda: self.create_modify_profile(False))
            self.ui.remove_profile_button.clicked.connect(self.remove_profile)
            self.ui.import_profile_action.triggered.connect(lambda: self.import_export_profile(True))
            self.ui.export_profile_action.triggered.connect(lambda: self.import_export_profile(False))
            self.update_timer.timeout.connect(self.updater)
            self.ui.submission_search_button.clicked.connect(self.search_content)
            self.ui.submission_clear_btn.clicked.connect(self.clear_content)
            self.ui.submission_delete_button.clicked.connect(self.delete_content)
            self.ui.submission_dump_button.clicked.connect(self.dump_content)
            self.ui.migrate_profile_button.clicked.connect(self.migrate_content)

            log("Functions connected successfully!")
        except Exception as e:
            log(e)

    def create_modify_profile(self, create):
        log("Opening profile menu...")

        try:
            self.profile_window = ProfileWindow(self, create)
            self.profile_window.exec_()
        except Exception as e:
            log(e)

    def remove_profile(self):
        remove_profile = QMessageBox.question(self, "Remove profile(s)?", "Are you sure you wish to remove profile(s)?")

        if remove_profile == QMessageBox.Yes:
            log("Removing profile...")

            try:
                for profile in range(len(self.ui.profile_list.selectedItems())):
                    try:
                        os.remove(f"profiles/{(self.ui.profile_list.selectedItems()[profile].text())}.rpf")
                        # If it can't find an .RPF file, it tries to delete a .TXT file.
                    except:
                        os.remove(f"profiles/{(self.ui.profile_list.selectedItems()[profile].text())}.txt")

                log("Profile(s) removed successfully!")
            except Exception as e:
                log(e)

    def import_export_profile(self, _import):
        if _import:
            log("Importing profile...")

            try:
                file_dialog = QFileDialog(self)
                options = QFileDialog.Options()
                options |= QFileDialog.DontUseNativeDialog
                filters = "Reddit Profile (*.rpf);;Text Files (*.txt)"
                import_file = file_dialog.getOpenFileName(self, "Import Profile", "", filter=filters, options=options)

                do_import = QMessageBox.Yes
                for user_file in os.listdir("profiles"):
                    if os.path.split(import_file[0])[1] == user_file:
                        do_import = QMessageBox.question(self, "Profile already exists",
                                                         "Profile already exists! Overwrite?",
                                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)

                if do_import == QMessageBox.Yes:
                    shutil.copyfile(import_file[0], f"profiles/{os.path.split(import_file[0])[1]}")

                    log("Profile imported successfully!")
            except Exception as e:
                log(e)
        else:
            log("Exporting profile...")

            try:
                file_dialog = QFileDialog(self)
                options = QFileDialog.Options()
                options |= QFileDialog.DontUseNativeDialog
                filters = "Reddit Profile (*.rpf);;Text Files (*.txt)"
                export_file = file_dialog.getSaveFileName(self, "Export Reddit Profile", "",
                                                          filter=filters, options=options)

                shutil.copyfile(f"profiles/{self.ui.profile_list.selectedItems()[0].text()}.rpf",
                                export_file[0] + export_file[1].split("*")[1][:-1])

                log("Profile exported successfully!")
            except Exception as e:
                log(e)

    def search_content(self):
        filters = {}

        search_text = self.ui.submission_search_bar.text()

        filters["Sort"] = self.ui.sort_combo.currentIndex()
        filters["Time"] = (self.ui.time_combo.currentIndex(), int(self.ui.time_edit.dateTime().toPython()
                                                                  .replace(tzinfo=datetime.timezone.utc).timestamp()))
        filters["Score"] = (self.ui.min_score_spin.value(), self.ui.max_score_spin.value())
        filters["Awarded"] = self.ui.award_combo.currentIndex()
        filters["Edited"] = self.ui.edited_combo.currentIndex()
        filters["Subreddit"] = self.ui.subreddit_edit.text().replace("r/", "")
        filters["Removed"] = self.ui.removed_combo.currentIndex()

        try:
            with open(f"profiles/{self.ui.profile_list.selectedItems()[0].text()}.rpf") as file:
                file_lines = file.readlines()
                profile = [line.replace("\n", "") for line in file_lines]

            log("Starting background thread...")

            self.ui.content_tree.clear()

            if self.ui.comment_radio.isChecked():
                self.background_thread = ThreadGatherComments(self, profile, search_text, filters)
                self.background_thread.output_comment.connect(self.add_comment_to_gui)
                self.current_search = "comments"
            else:
                self.background_thread = ThreadGatherPosts(self, profile, search_text, filters)
                self.background_thread.output_post.connect(self.add_post_to_gui)
                self.current_search = "posts"

            self.background_thread.thread_progress.connect(self.set_progress)
            self.background_thread.thread_status.connect(self.set_status)
            self.background_thread.start()

            self.current_process = "Search"
        except Exception as e:
            log(e)

    def add_comment_to_gui(self, comment):
        try:
            comment_id = comment["id"]
            comment_date = datetime.datetime.fromtimestamp(comment["data"]["created"]).strftime('%m/%d/%Y %I:%M %p')
            comment_removed = comment["data"]["removed"]
            comment_body = textwrap.wrap(comment["data"]["body"], 55)
            comment_subreddit = comment["data"]["subreddit"]
            comment_link = f"https://www.reddit.com{comment['data']['permalink']}"
            comment_score = comment["data"]["score"]
            comment_edited = "Yes" if comment["data"]["edited"] else "No"
            if comment["data"]["awarded"] != "Unknown":
                comment_awarded = "Yes" if comment["data"]["awarded"] else "No"
            else:
                comment_awarded = "Unknown"

            comment_branch = QTreeWidgetItem([comment_id, comment_date, comment_removed])
            comment_body_sub_branch = QTreeWidgetItem(["Body"])
            comment_subreddit_leaf = QTreeWidgetItem([f"Subreddit: r/{comment_subreddit}"])
            comment_score_leaf = QTreeWidgetItem([f"Score: {comment_score}"])
            comment_edited_leaf = QTreeWidgetItem([f"Edited: {comment_edited}"])
            comment_awarded_leaf = QTreeWidgetItem([f"Awarded: {comment_awarded}"])
            comment_link_leaf = QTreeWidgetItem(["L͟i͟n͟k͟"])

            self.ui.content_tree.addTopLevelItem(comment_branch)
            comment_branch.addChildren([comment_body_sub_branch, comment_subreddit_leaf, comment_score_leaf,
                                        comment_edited_leaf, comment_awarded_leaf, comment_link_leaf])
            comment_body_sub_branch.addChildren([QTreeWidgetItem([line]) for line in comment_body])

            for c in [comment_branch.child(c) for c in range(comment_branch.childCount())]:
                c.setFlags(c.flags() & ~Qt.ItemIsSelectable)
            for c in [comment_body_sub_branch.child(c) for c in range(comment_body_sub_branch.childCount())]:
                c.setFlags(c.flags() & ~Qt.ItemIsSelectable)

            if comment["index"] % 2 == 0:
                comment_branch.setBackgroundColor(0, QColor(220, 220, 220))
                comment_branch.setBackgroundColor(1, QColor(220, 220, 220))

            comment_link_leaf.setTextColor(0, QColor(0, 0, 238))
            comment_link_leaf.setStatusTip(0, comment_link)

            if comment["data"]["removed"]:
                comment_branch.setTextColor(0, QColor(255, 0, 0))
                comment_branch.setStatusTip(0, "Removed Content")
            else:
                comment_branch.setStatusTip(0, "Reddit Content")

        except Exception as e:
            log(e)

    def add_post_to_gui(self, post):
        try:
            post_id = post["id"]
            post_date = datetime.datetime.fromtimestamp(post["data"]["created"]).strftime('%m/%d/%Y %I:%M %p')
            post_title = textwrap.wrap(post["data"]["title"], 55)
            post_removed = post["data"]["removed"]
            post_selftext = textwrap.wrap(post["data"]["selftext"], 55)
            post_subreddit = post["data"]["subreddit"]
            post_link = f"https://www.reddit.com{post['data']['permalink']}"
            post_score = post["data"]["score"]
            post_edited = "Yes" if post["data"]["edited"] else "No"
            if post["data"]["awarded"] != "Unknown":
                post_awarded = "Yes" if post["data"]["awarded"] else "No"
            else:
                post_awarded = "Unknown"

            post_branch = QTreeWidgetItem([post_id, post_date, post_removed])
            post_selftext_sub_branch = QTreeWidgetItem(["SelfText"])
            post_title_sub_branch = QTreeWidgetItem(["Title"])
            post_subreddit_leaf = QTreeWidgetItem([f"Subreddit: r/{post_subreddit}"])
            post_score_leaf = QTreeWidgetItem([f"Score: {post_score}"])
            post_edited_leaf = QTreeWidgetItem([f"Edited: {post_edited}"])
            post_awarded_leaf = QTreeWidgetItem([f"Awarded: {post_awarded}"])
            post_link_leaf = QTreeWidgetItem(["L͟i͟n͟k͟"])

            self.ui.content_tree.addTopLevelItem(post_branch)
            post_branch.addChildren([post_title_sub_branch, post_selftext_sub_branch, post_subreddit_leaf,
                                     post_score_leaf, post_edited_leaf, post_awarded_leaf, post_link_leaf])
            post_selftext_sub_branch.addChildren([QTreeWidgetItem([line]) for line in post_selftext])
            post_title_sub_branch.addChildren([QTreeWidgetItem([line]) for line in post_title])

            if post["data"]["selftext"] == "":
                post_branch.takeChild(1)

            for c in [post_branch.child(c) for c in range(post_branch.childCount())]:
                c.setFlags(c.flags() & ~Qt.ItemIsSelectable)
            for c in [post_selftext_sub_branch.child(c) for c in range(post_selftext_sub_branch.childCount())]:
                c.setFlags(c.flags() & ~Qt.ItemIsSelectable)

            if post["index"] % 2 == 0:
                post_branch.setBackgroundColor(0, QColor(220, 220, 220))
                post_branch.setBackgroundColor(1, QColor(220, 220, 220))

            post_link_leaf.setTextColor(0, QColor(0, 0, 238))
            post_link_leaf.setStatusTip(0, post_link)

            if post["data"]["removed"]:
                post_branch.setTextColor(0, QColor(255, 0, 0))
                post_branch.setStatusTip(0, "Removed Content")
            else:
                post_branch.setStatusTip(0, "Reddit Content")

        except Exception as e:
            log(e)

    def set_progress(self, progress):
        self.ui.submission_progress_bar.setValue(progress)

    def set_status(self, status):
        self.ui.submission_progress_status.setText(status)

    def clear_content(self):
        while len(self.ui.content_tree.selectedItems()) != 0:
            for index in range(self.ui.content_tree.topLevelItemCount()):
                if isinstance(self.ui.content_tree.topLevelItem(index), QTreeWidgetItem):
                    if self.ui.content_tree.topLevelItem(index).isSelected():
                        self.ui.content_tree.takeTopLevelItem(index)

    def delete_content(self):
        with open(f"profiles/{self.current_profile}.rpf") as file:
            file_lines = file.readlines()

            profile = [line.replace("\n", "") for line in file_lines]

        self.background_thread = ThreadDeleteContent(self, profile)
        self.background_thread.thread_status.connect(self.set_status)
        self.background_thread.thread_progress.connect(self.set_progress)
        self.background_thread.remove_comment.connect(self.remove_content_from_gui)
        self.background_thread.start()

        self.current_process = "Delete"

    def remove_content_from_gui(self, index):
        self.ui.content_tree.takeTopLevelItem(index)

    def open_link(self, item):
        if item.text(0) == "L͟i͟n͟k͟":
            webbrowser.open(item.statusTip(0))
            item.setTextColor(0, QColor(85, 26, 139))

    def dump_content(self):
        file_dialog = QFileDialog(self)
        options = QFileDialog.Options()
        options |= QFileDialog.DontUseNativeDialog
        filters = "JSON (*.json);;HTML (*.html);;Comma-separated (*.csv)"
        save_file = file_dialog.getSaveFileName(self, "reddit file", "", filter=filters, options=options)

        log("Dumping data to file...")

        if self.current_search == "comments":
            content_data = pandas.DataFrame(columns=["id", "created", "body", "subreddit", "score",
                                                     "edited", "awarded", "link"])

            for item in self.ui.content_tree.selectedItems():
                id = item.text(0)
                created = item.text(1)
                body = " ".join([item.child(0).child(i).text(0) for i in range(item.child(0).childCount())])
                subreddit = item.child(1).text(0)
                score = item.child(2).text(0)
                edited = item.child(3).text(0)
                awarded = item.child(4).text(0)
                link = item.child(5).statusTip(0)

                content_data.loc[len(content_data)] = [id, created, body, subreddit, score, edited, awarded, link]
        else:
            content_data = pandas.DataFrame(columns=["id", "created", "title", "selftext", "subreddit", "score",
                                                     "edited", "awarded", "link"])

            for item in self.ui.content_tree.selectedItems():
                shift = 0
                if item.child(1).text(0) == "SelfText":
                    selftext = " ".join([item.child(1).child(i).text(0) for i in range(item.child(1).childCount())])
                else:
                    selftext = None
                    shift = 1

                id = item.text(0)
                created = item.text(1)
                title = " ".join([item.child(0).child(i).text(0) for i in range(item.child(0).childCount())])
                subreddit = item.child(2 - shift).text(0)
                score = item.child(3 - shift).text(0)
                edited = item.child(4 - shift).text(0)
                awarded = item.child(5 - shift).text(0)
                link = item.child(6 - shift).statusTip(0)

                content_data.loc[len(content_data)] = [id, created, title, selftext, subreddit,
                                                       score, edited, awarded, link]

        if "json" in save_file[1]:
            content_data.to_json(save_file[0] + "".join(save_file[1].split("*")[1][:-1]))
        elif "html" in save_file[1]:
            content_data.to_html(save_file[0] + "".join(save_file[1].split("*")[1][:-1]), index=False)
        elif "csv" in save_file[1]:
            content_data.to_csv(save_file[0] + "".join(save_file[1].split("*")[1][:-1]), index=False)

        log(f'Done dumping content to {save_file[0] + "".join(save_file[1].split("*")[1][:-1])}')

    def migrate_content(self):
        log("Migrating subs...")

        with open(f"profiles/{self.ui.profile_list.selectedItems()[0].text()}.rpf") as file:
            file_lines = file.readlines()

            profile_to = [line.replace("\n", "") for line in file_lines]

        with open(f"profiles/{self.ui.profile_list.selectedItems()[1].text()}.rpf") as file:
            file_lines = file.readlines()

            profile_from = [line.replace("\n", "") for line in file_lines]

        reddit = praw.Reddit(username=profile_from[0],
                             password=profile_from[1],
                             client_id=profile_from[2],
                             client_secret=profile_from[3],
                             user_agent="Reddit Content Manager")

        subreddits = [subreddit.display_name for subreddit in reddit.user.subreddits(limit=100)]

        reddit = praw.Reddit(username=profile_to[0],
                             password=profile_to[1],
                             client_id=profile_to[2],
                             client_secret=profile_to[3],
                             user_agent="Reddit Content Manager")

        for subreddit in subreddits:
            try:
                subreddit = reddit.subreddit(subreddit)
                subreddit.subscribe()
            except Exception as e:
                log(e)

        log("Done migrating subreddits!")


def log(log_string):
    global log_file

    if not os.path.isdir("logs"):
        os.mkdir("logs")

    if not os.path.isfile(log_file):
        open(log_file, "w+").close()

    with open(log_file, "a+") as file:
        file.write(f"({datetime.datetime.now()}) - {log_string}\n")

    print(f"({datetime.datetime.now()}) - {log_string}")


def main():
    log("Starting program...")

    try:
        app = QApplication(sys.argv)

        window = MainWindow()
        window.show()

        sys.exit(app.exec_())
    except Exception as e:
        log(e)


if __name__ == '__main__':
    main()
