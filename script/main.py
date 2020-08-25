import sys
import copy
from enum import Enum
from typing import List, TypedDict, Union
import json
from os import environ, path
import time
import requests
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
from slack import WebClient
from slack.web.base_client import SlackResponse
from slackblocks import Message, SectionBlock, Text
from pydash import find
from dotenv import load_dotenv
from logger import logger

load_dotenv()

args = sys.argv

if len(args) < 2:
    raise Exception('argument must be required for product data json')

TARGET_ORIGIN = 'https://ec.snowpeak.co.jp'
# スノーピーク（アウトドア・キャンプ用品の通販）TOP > キャンプ
TARTGET_URL = TARGET_ORIGIN + \
    '/snowpeak/ja/%E3%82%AD%E3%83%A3%E3%83%B3%E3%83%97/c/2010000' # pylint: disable=line-too-long
PAGINATION_CLASS_NAME = 'pagination'
PRODUCTS_CONTAINER_SELECTOR = '.results-all-product.productItemForList'
PRODUCTS_SELECTOR = PRODUCTS_CONTAINER_SELECTOR + ' > div'
NO_RESULT_FOUND_SELECTOR = '.category-empty'
PRODUCT_DATA_JSON = args[1]  # '.product_data.json'

class Product(TypedDict):
    id: str
    labels: List[str]

class ArrivalType(Enum):
    NEW = "新商品"
    RESTOCK = "再入荷"


class ProductState(Enum):
    SOLDOUT = "入荷待ち"
    INSTOCK = "在庫あり"

class Helper:
    @classmethod
    def pick_label_texts(cls, product_soup: BeautifulSoup) -> List[str]:
        product_labels: List[BeautifulSoup] = product_soup.select(
            '.product-label > p')
        return list(map(lambda l: l.get_text(strip=True), product_labels))

    @classmethod
    def pick_product_id(cls, product_soup: BeautifulSoup) -> str:
        _s: List[BeautifulSoup] = product_soup.select('[data-product-id]')
        return _s[0]['data-product-id']

    @classmethod
    def pick_product_href(cls, product_soup: BeautifulSoup) -> str:
        _a: List[BeautifulSoup] = product_soup.select('.thumbnail.product a')
        return _a[0]['href']

    @classmethod
    def pick_product_name(cls, product_soup: BeautifulSoup) -> str:
        name_soup_list: List[BeautifulSoup] = product_soup.select('.product-info .name')
        return name_soup_list[0].get_text(strip=True)

    @classmethod
    def get_arrival_type(cls, stored_product: Union[Product, None]) -> str:
        if stored_product is None:
            return ArrivalType.NEW.value
        return ArrivalType.RESTOCK.value

    @classmethod
    def should_notify(cls, product_soup: BeautifulSoup, stored_product: Union[Product, None]) -> bool:
        if stored_product is None:
            return True
        if ProductState.SOLDOUT.value in stored_product['labels']:
            labels = Helper.pick_label_texts(product_soup)
            if ProductState.SOLDOUT.value not in labels:
                return True
        return False

class Products:
    def __init__(self, stored_data_path: str):
        _p: List[Product] = []
        self.data = {"date": time.time(), "products": _p}
        if path.exists(stored_data_path):
            json_open = open(stored_data_path, 'r')
            self.__stored_data = json.load(json_open)
        else:
            self.__stored_data = None

    def add_data(self, product_soup: BeautifulSoup) -> None:
        labels = Helper.pick_label_texts(product_soup)
        product_id = Helper.pick_product_id(product_soup)
        self.data["products"].append({"id": product_id, "labels": labels})

    @property
    def stored_data(self):
        return self.__stored_data

    @stored_data.getter
    def stored_data(self):
        return self.__stored_data

class SlackMessage:
    def __init__(self, slack_api_token: str, channel: str):
        self.blocks = []
        self.client = WebClient(token=slack_api_token)
        self.channel = channel

    def add_product(self, name: str, url: str, arrival_type: str) -> None:
        text = Text(text="%s!!!\n\n> <%s|%s>" % (arrival_type, url, name))
        self.blocks.append(SectionBlock(text=text))

    def send_message(self) -> SlackResponse:
        message = Message(channel=self.channel, blocks=self.blocks)
        return self.client.chat_postMessage(**message)

def process_product(product_soup: BeautifulSoup, products: Products,
    slack_message: SlackMessage) -> None:
    products.add_data(product_soup)

    stored_data = products.stored_data

    if stored_data:
        product_id = Helper.pick_product_id(product_soup)
        stored_product = find(stored_data['products'], {'id': product_id})
        if Helper.should_notify(product_soup, stored_product):
            name = Helper.pick_product_name(product_soup)
            href = Helper.pick_product_href(product_soup)
            arrival_type = Helper.get_arrival_type(stored_product)
            slack_message.add_product(name, TARGET_ORIGIN + href, arrival_type)

def main():
    user_agent = UserAgent()
    slack_message = SlackMessage(environ["SLACK_API_TOKEN"], "#snowpeak")
    products = Products(PRODUCT_DATA_JSON)

    # ?q = %3Acreationtime & page = 1
    base_params = {"q": ":creationtime"}
    page = 0
    while True:
        params = copy.copy(base_params)
        params["page"] = page
        _u = user_agent.chrome
        logger.debug(_u)
        headers = {'User-Agent': _u}
        res = requests.get(TARTGET_URL, headers=headers, params=params)
        logger.debug(res.url)
        if res.status_code != 200:
            logger.debug('target page is not working')
            continue

        soup = BeautifulSoup(res.text, 'lxml')

        no_result_found = soup.body.select(NO_RESULT_FOUND_SELECTOR)

        if len(no_result_found) != 0:
            break

        product_soup_list = soup.body.select(PRODUCTS_SELECTOR)

        for product_soup in product_soup_list:
            process_product(product_soup, products, slack_message)

        page += 1

    with open(PRODUCT_DATA_JSON, 'w') as _f:
        json.dump(products.data, _f, ensure_ascii=False)

    if len(slack_message.blocks) > 0:
        slack_message.send_message()

if __name__ == '__main__':
    sys.exit(main())
