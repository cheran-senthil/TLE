from bs4 import BeautifulSoup
import requests

def assert_display_name(username, token, resource, mention):
    if resource=='codechef.com':
        response = requests.get("https://codechef.com/users/"+str(username))
        if response.status_code != 200:
            return False
        else:
            soup = BeautifulSoup(response.content, 'html.parser')
            elements = soup.find_all(class_='h2-style')
            for element in elements:
                if token in element.text:
                    return True
    elif resource=='atcoder.jp':
        response = requests.get("https://atcoder.jp/users/"+str(username))
        if response.status_code != 200:
            return False
        else:
            soup = BeautifulSoup(response.content, 'html.parser')
            elements = soup.find_all(class_='break-all')
            for element in elements:
                if token in element.text:
                    return True
    return False