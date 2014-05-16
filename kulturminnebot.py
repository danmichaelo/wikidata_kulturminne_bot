import re
import sys
import logging
import time
import codecs

import urllib
import urllib2
import simplejson as json
from cookielib import CookieJar

import mwclient
from mwtemplates import TemplateEditor

config = json.load(open('config.json', 'r'))

logging.basicConfig(level=logging.INFO)

cj = CookieJar()
opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(cj))
opener.addheaders = [('User-agent', 'DanmicholoBot')]

# https://www.mediawiki.org/wiki/Maxlag
lagpattern = re.compile(r'Waiting for [^ ]*: (?P<lag>[0-9.]+) seconds? lagged')


def raw_api_call(args):
    while True:
        url = 'https://www.wikidata.org/w/api.php'
        args['format'] = 'json'
        args['maxlag'] = 5
        #print args

        for k, v in args.iteritems():
            if type(v) == unicode:
                args[k] = v.encode('utf-8')
            else:
                args[k] = v

        #print args
        #logging.info(args)

        data = urllib.urlencode(args)

        response = opener.open(url, data=data)
        #print response.info()
        response = json.loads(response.read())

        #logging.info(response)

        if 'error' not in response:
            return response

        code = response['error'].pop('code', 'Unknown')
        info = response['error'].pop('info', '')
        if code == 'maxlag':
            lag = lagpattern.search(info)
            if lag:
                logging.warn('Pausing due to database lag: %s', info)
                time.sleep(int(lag.group('lag')))
                continue

        logging.error('Unknown API error: %s', info)
        print args
        sys.exit(1)


def login(user, pwd):
    args = {
        'action': 'login',
        'lgname': user,
        'lgpassword': pwd
    }
    response = raw_api_call(args)
    if response['login']['result'] == 'NeedToken':
        args['lgtoken'] = response['login']['token']
        response = raw_api_call(args)

    return (response['login']['result'] == 'Success')


def pageinfo(entity):
    args = {
        'action': 'query',
        'prop': 'info',
        'intoken': 'edit',
        'titles': entity
    }
    return raw_api_call(args)


def get_entities(site, page):
    args = {
        'action': 'wbgetentities',
        'sites': site,
        'titles': page
    }
    return raw_api_call(args)


def get_claims(entity, property):
    args = {
        'action': 'wbgetclaims',
        'entity': entity,
        'property': property
    }
    return raw_api_call(args)


def create_claim(entity, property, value):

    response = pageinfo(entity)
    itm = response['query']['pages'].items()[0][1]
    baserevid = itm['lastrevid']
    edittoken = itm['edittoken']

    args = {
        'action': 'wbcreateclaim',
        'bot': 1,
        'entity': entity,
        'property': property,
        'snaktype': 'value',
        'value': json.dumps(value),
        'token': edittoken,
        'baserevid': baserevid
    }
    logging.info("  Sleeping 4 secs")
    time.sleep(4)
    response = raw_api_call(args)
    return response


def set_reference(entity, statement, snaks):

    response = pageinfo(entity)
    itm = response['query']['pages'].items()[0][1]
    baserevid = itm['lastrevid']
    edittoken = itm['edittoken']

    args = {
        'action': 'wbsetreference',
        'bot': 1,
        'statement': statement,
        'snaks': json.dumps(snaks),
        'token': edittoken,
        'baserevid': baserevid
    }
    logging.info("  Sleeping 2 secs")
    time.sleep(2)
    return raw_api_call(args)


def create_claim_if_not_exists(entity, property, value):

    response = get_claims(entity, property)

    if property in response['claims']:
        curval = response['claims'][property][0]['mainsnak']['datavalue']['value']
        if value == curval:
            logging.info('  %s: Claim already exists with the same value', entity)
        else:
            logging.warn('  %s: Claim already exists. Existing value: %s, new value: %s', entity, curval, value)
        return None

    logging.info('  %s: Claim does not exist', entity)

    return create_claim(entity, property, value)


def add_kulturminne_id(page, kulturminne_id):
    response = get_entities('nowiki', page)
    q_number = response['entities'].keys()[0]
    if q_number == '-1':
        logging.error('Finnes ingen wikidataside for %s', page)
    else:

        logging.info('Page: %s (%s), id = %s', page, q_number, kulturminne_id)

        response = create_claim_if_not_exists(q_number, 'P758', kulturminne_id)
        if response:

            logging.info('  Added kulturminne_id = %s to %s (%s)', kulturminne_id, page, q_number)

            statement = response['claim']['id']

            snaks = {'P143': [
                {
                    'snaktype': 'value',
                    'property': 'P143',
                    'datavalue': {
                        'type': 'wikibase-entityid',
                        'value': {
                            'entity-type': 'item',
                            'numeric-id': 191769    # nowp
                        }
                    }
                }]}
            set_reference(q_number, statement, snaks)

        if create_claim_if_not_exists(q_number, 'P17', {'entity-type': 'item', 'numeric-id': 20}):
            logging.info('  Added land = Norge to %s (%s)', page, q_number)

        if create_claim_if_not_exists(q_number, 'P31', {'entity-type': 'item', 'numeric-id': 2065736}):
            logging.info('  Added instans av = kulturminne to %s (%s)', page, q_number)


if login(config['user'], config['pass']):
    logging.info('Hurra, vi er innlogga')
else:
    logging.error('Innloggingen feilet')
    sys.exit(1)


nowp = mwclient.Site('no.wikipedia.org')

checkedfile = codecs.open('checked.txt', 'r', encoding='UTF-8')
checked = [s.strip("\n") for s in checkedfile.readlines()]
checkedfile.close()

logging.info("Ignoring %d files already checked" % len(checked))

checkedfile = codecs.open('checked.txt', 'a', encoding='UTF-8', buffering=0)
inspectfile = codecs.open('requires_inspection.txt', 'w', encoding='UTF-8', buffering=0)

tpl = nowp.pages['Mal:Kulturminne']
n = 0
for page in tpl.embeddedin(namespace=0):
    #page = nowp.pages['Oslo domkirke']
    if page.page_title not in checked:
        txt = page.edit(readonly=True)
        te = TemplateEditor(txt)
        if len(te.templates['Kulturminne']) != 1:
            ider = [x.parameters[1].value for x in te.templates['Kulturminne']]
            line = "%s;%s\n" % (page.page_title, '@'.join(ider))
            inspectfile.write(line)
            continue
        else:
            # python string formattingpython string formatting
            kulturminne_id = te.templates['Kulturminne'][0].parameters[1].value
            if len(kulturminne_id) < 3:
                logging.warn('Seems to be an error with %s', page.page_title)
                continue

        add_kulturminne_id(page.page_title, kulturminne_id)
        n += 1
        checkedfile.write(page.page_title + "\n")
        #break
