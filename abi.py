# -*- coding: utf-8 -*-
"""
Created on Sun Apr 29 10:11:13 2024

"""

from bs4 import BeautifulSoup as bsp
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from webdriver_manager.firefox import GeckoDriverManager


def tokenAbi(address, driver=None):
    try:
        filename = f'ABI_{address}.txt'
        with open(f"data/{filename}") as f:
            abi = f.readlines()
            return abi[0]
    except IOError:
        abi = findAbi(address, driver)
        return abi


def findAbi(address, driver):
    url = f'https://bscscan.com/address/{address}#code'

    if not driver:
        options = Options()
        options.headless = True
        driver = webdriver.Firefox(executable_path=GeckoDriverManager().install(), options=options)

    driver.get(url)
    page_soup = bsp(driver.page_source, features="lxml")
    abi = page_soup.find_all("pre", {"class": "wordwrap js-copytextarea2"})

    with open(f'data/ABI_{address}.txt', 'w') as f:
        f.write(abi[0].text)

    driver.delete_all_cookies()
    driver.get("chrome://settings/clearBrowserData");
    # driver.close()
    return abi[0].text
