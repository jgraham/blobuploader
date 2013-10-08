#!/usr/bin/env python
"""Usage: blobberc.py -u URL... -a AUTH_FILE -b BRANCH [-v] [-d] FILE

-u, --url URL          URL to blobber server to upload to.
-a, --auth AUTH_FILE   user/pass AUTH_FILE for signing the calls
-b, --branch BRANCH    Specify branch for the file (e.g. try, mozilla-central)
-v, --verbose          Increase verbosity
-d, --dir              Instead of a file, upload multiple files from a dir name

FILE                   Local file(s) to upload
"""
import urlparse
import os
import hashlib
import requests
import logging
import random
from functools import partial

from blobuploader import cert

log = logging.getLogger(__name__)


def filehash(filename, hashalgo):
    h = hashlib.new(hashalgo)
    with open(filename, 'rb') as f:
        for block in iter(partial(f.read, 1024 ** 2), ''):
            h.update(block)
    return h.hexdigest()


def upload_file(hosts, filename, branch, auth, hashalgo='sha512',
                blobhash=None, attempts=10):

    if blobhash is None:
        blobhash = filehash(filename, hashalgo)

    log.info("Try to upload %s ..." % filename)
    host_pool = hosts[:]
    random.shuffle(host_pool)
    n = 1

    file_uploaded = False
    while n <= attempts and host_pool:
        host = host_pool.pop()
        log.info("Picked up %s host after shuffling." % host)

        log.info("POST call the file - attempt #%d." % (n))
        resp = _post_file(host, auth, filename, branch,
                          hashalgo, blobhash)

        ret_code = resp.status_code
        if ret_code == 202:
            # File posted successfully via blob server.
            # Make sure the resource is available on amazon S3 bucket.
            blob_url = resp.headers.get('x-blob-url')
            if not blob_url:
                log.warning("Blob resource URL not found in response.")
                break

            ret = requests.head(blob_url)
            if ret.ok:
                log.info("Uploaded %s to %s" % (filename, blob_url))
                file_uploaded = True
            else:
                log.warning("Uploaded file on blobserver but failed to find it "
                            "to Amazon S3.")
            break
        elif ret_code == 403 or ret_code == 401:
            # avoid attempting to make same wrong call to other servers
            break
        else:
            log.warning("POST call failed. Trying again ...")

        n += 1

    if not file_uploaded:
        log.warning("Uploading %s file failed!" % (filename))


def _post_file(host, auth, filename, branch, hashalgo, blobhash):
    url = urlparse.urljoin(host, '/blobs/{}/{}'.format(hashalgo, blobhash))

    data_dict = {
        'blob': open(filename, "rb"),
    }
    meta_dict = {
        'branch': branch,
    }

    log.debug("Posting file to %s ...", url)
    response = requests.post(url,
                             auth=auth,
                             files=data_dict,
                             data=meta_dict,
                             verify=cert.where(),
    )
    if response.status_code != 202:
        err_msg = response.headers.get('x-blobber-msg',
                                       'Something went wrong on blobber!')
        log.warning(err_msg)

    return response


def upload_dir(hosts, dirname, branch, auth, hashalgo='sha512'):
    log.info("Open directory for files ...")
    dir_files = [f for f in os.listdir(dirname)
                 if os.path.isfile(os.path.join(dirname, f))]

    log.debug("Go through all files in directory")
    for f in dir_files:
        filename = os.path.join(dirname, f)
        upload_file(hosts, filename, branch, auth)

    log.info("Iteration through files over.")


def main():
    from docopt import docopt

    args = docopt(__doc__)

    if args['--verbose']:
        loglevel = logging.DEBUG
    else:
        loglevel = logging.INFO

    FORMAT = "(blobuploader) - %(levelname)s - %(message)s"
    logging.basicConfig(format=FORMAT, level=loglevel)
    logging.getLogger('requests').setLevel(logging.WARN)

    credentials = {}
    execfile(args['--auth'], credentials)
    auth = (credentials['blobber_username'], credentials['blobber_password'])

    if args['--dir']:
        if os.path.isdir(args['FILE']):
            upload_dir(args['--url'],
                       args['FILE'],
                       args['--branch'],
                       auth)
    else:
        if os.path.isfile(args['FILE']):
            upload_file(args['--url'],
                        args['FILE'],
                        args['--branch'],
                        auth)


if __name__ == '__main__':
    main()
