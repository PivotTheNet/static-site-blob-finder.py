#!/bin/python3

# static-site-blob-finder.py

# What does static-site-blob-finder.py do?
# - Enumerates anonymously accessible Azure Blob Storage containers that host static websites.
# - Searches for current and previous blob versions.
# - Allows the operator to interactively download any found blobs.

# Import regex module
import re
# Import system functions module. For exits and user input.
import sys
# Import os module. For directory and file operations, e.g., creating directories etc
import os
# Import requests module for HTTP(s) requests to fetch web pages and blobs.
import requests
# For parsing XML data, which is how Azure returns blob listings.
from lxml import etree
# For parsing HTML to extract blob storage URLs.
from bs4 import BeautifulSoup
# For parsing URLs. e.g., extracting the domain.
from urllib.parse import urlparse
# For terminal colors. Makes it easier to read and determine what you may want to download.
from colorama import init, Fore, Style

# Resets colors after each print command.
init(autoreset=True)

# Searches URL 
def extract_blob_container_url(html):
    soup = BeautifulSoup(html, "html.parser")
    urls = set()
    for tag in soup.find_all(['a', 'link', 'script', 'img']):
        for attr in ['href', 'src']:
            val = tag.get(attr)
            if val and "blob.core.windows.net" in val:
                urls.add(val)
    if not urls:
        print(Fore.RED + "No Azure Blob Storage URLs found in the HTML.")
        sys.exit(1)
    url = list(urls)[0]
    print(Fore.GREEN + f"Found Azure Blob Storage URL: {url}")
    return url

def parse_storage_account_and_container(blob_url):
    m = re.match(r"https://([^.]+)\.blob\.core\.windows\.net/([^/]+)/", blob_url)
    if not m:
        print(Fore.RED + "Could not parse storage account and container from URL.")
        sys.exit(1)
    storage_account, container = m.group(1), m.group(2)
    print(Fore.GREEN + f"Storage account: {storage_account}, Container: {container}")
    return storage_account, container

# function to enumerate blobs within found container using Azure API
def enumerate_blobs(storage_account, container):
    # string formatted to include variables
    endpoint = f"https://{storage_account}.blob.core.windows.net/{container}?restype=container&comp=list&include=versions"
    # set version header to include blobs saved by versioning
    headers = {"x-ms-version": "2019-12-12"}
    # variable holding request to API using endpoint and header variables
    resp = requests.get(endpoint, headers=headers)
    # raise error as needed
    resp.raise_for_status()
    # return string parsed as element
    return etree.fromstring(resp.content)
# Extract needed relevant info from each blob from the xml element. Return list of dictionaries, each being a blob/version.
def list_blobs(xml_root):
    blobs = []
    for blob in xml_root.xpath('.//Blob'):
        name = blob.findtext('Name')
        version = blob.findtext('VersionId')
        is_current = blob.findtext('IsCurrentVersion')
        size = blob.findtext('Properties/Content-Length')
        content_type = blob.findtext('Properties/Content-Type')
        blobs.append({
            'name': name,
            'version': version,
            'is_current': is_current,
            'size': size,
            'content_type': content_type
        })
    return blobs

# CLeans up file paths in dictionary
def sanitize_path(path):
    # Allow slashes for directories, but replace anything else problematic
    return re.sub(r'[^A-Za-z0-9._/\-]', '_', path)

# Converts user input into a sorted list of valid blob indices (1-based). Returns list of select indices.
def parse_selection(selection, max_index):
    """Parse user input like '1,3,5-7' into a set of indices."""
    result = set()
    for part in selection.split(','):
        part = part.strip()
        if '-' in part:
            start, end = part.split('-')
            result.update(range(int(start), int(end)+1))
        elif part.isdigit():
            result.add(int(part))
    # Only keep valid indices
    return sorted(i for i in result if 1 <= i <= max_index)

# Downloads the selected blob/version, saving it under the correct directory structure.
def download_blob(storage_account, container, blob, base_dir):
    # url structure for downloads selected
    url = f"https://{storage_account}.blob.core.windows.net/{container}/{blob['name']}"
    headers = {"x-ms-version": "2019-12-12"}
    if blob['version']:
        url += f"?versionid={blob['version']}"
    rel_path = sanitize_path(blob['name'])
    if blob['version']:
        safe_version = sanitize_path(blob['version'])
        parts = rel_path.rsplit('.', 1)
        if len(parts) == 2:
            rel_path = f"{parts[0]}.{safe_version}.{parts[1]}"
        else:
            rel_path = f"{rel_path}.{safe_version}"
    out_path = os.path.join(base_dir, rel_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    print(Fore.CYAN + f"Downloading {out_path} ...")
    r = requests.get(url, headers=headers, stream=True)
    if not r.ok:
        print(Fore.RED + f"Failed to download: {r.status_code} {r.reason}. URL tried: {url}")
        return
    with open(out_path, 'wb') as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)
    print(Fore.GREEN + f"Saved as {out_path}")

# Main Function
def main():
    # Make sure user supplies required argument.
    if len(sys.argv) != 2:
        # If not, print usage format. No help menu as this is simple script.
        print(Fore.YELLOW + 
            "Usage:\npython3 ./static-site-blob-finder.py '<static-site-url>'\nOR\nsudo chmod +x ./static-site-blob-finder.py\n./static-site-blob-finder.py '<static-site-url>'")        
        sys.exit(1)
    # set URL provided as site_url variable.
    site_url = sys.argv[1]
    # Print status for fetching the URLs source code, so it can be parsed and searched.
    print(Fore.CYAN + f"Fetching {site_url} ...")
    # resp variable set to requests module of .get using provides user var arg
    resp = requests.get(site_url)
    # show error is there is one
    resp.raise_for_status()
    # set blob_url variable to running extract_blob_container_url passing the resp.text resp with text
    blob_url = extract_blob_container_url(resp.text)
    # Regex and parse storage and container details from matching URL format of azure blob container
    storage_account, container = parse_storage_account_and_container(blob_url)
    # Use urlparse to extract netloc. Replace any : with _ to work with API
    site_netloc = urlparse(site_url).netloc.replace(':', '_')
    # Create base directory using site_netloc prepending downloads_
    base_dir = os.path.join(os.getcwd(), f"downloads_{site_netloc}")
    print(Fore.GREEN + f"Files will be saved under: {base_dir}")
    print(Fore.CYAN + "Enumerating blobs and versions...")
    #enumerate blobs in container. return parsed element
    xml_root = enumerate_blobs(storage_account, container)
    # xml_root returned with etree element in xml format
    blobs = list_blobs(xml_root)
    print(Fore.YELLOW + f"Found {len(blobs)} blobs (including versions).\n")
    # List all blobs with numbers and color by parsing needed into and assigning in dictionary
    for idx, blob in enumerate(blobs, 1):
        name_col = Fore.YELLOW + Style.BRIGHT
        size_col = Fore.GREEN
        type_col = Fore.MAGENTA
        ver_col = Fore.BLUE
        current_col = (Fore.GREEN if blob.get('is_current') == 'true' else Fore.RED)
        print(
            Fore.CYAN + Style.BRIGHT + f"{idx:2d}. " +
            name_col + f"{blob['name']}" +
            size_col + f" | Size: {blob['size']}" +
            type_col + f" | Type: {blob['content_type']}" +
            ver_col + f" | Version: {blob['version']}" +
            current_col + f" | Current: {blob.get('is_current')}"
        )
    # Prompt for selection. Downloaded files selected indices. Loop to download.
    print()
    selection = input(Fore.CYAN + "Enter file numbers to download (e.g. 1,3,5-7): " + Style.RESET_ALL).strip()
    if not selection:
        print(Fore.YELLOW + "No files selected.")
        return
    indices = parse_selection(selection, len(blobs))
    if not indices:
        print(Fore.RED + "No valid selections.")
        return
    for i in indices:
        download_blob(storage_account, container, blobs[i-1], base_dir)

if __name__ == '__main__':
    main()


# Updated on 4/29/2025

###################### CREATED BY revsh3ll ########################
##################### PivotTheNet.github.io #######################
##################### github.com/PivotTheNet ######################
#          #        (#         #                                  #
#           #%#       %%#       ##(                               #
#             #&&%#    %%%#       %%%                             #
#    ,##/ *#%&&&&&&&&#  &&&&&.       &&%.                         #
#                 #&&&&&&&#%&&&&* #&   #&&&                       #
#       &&&&&&&&&&&&&&&&&&&&&&&&&&&&&  & #&&&. #  *               #
#     %            #&&&&&&&&&&&&&&&&&& &&/#&&&# &# ##             #
#         #&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&%&%#&#            #
#      &&#     ,%&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&%&&&&&&            #
#          #&&&&&&&&&&&&&&&&&&&&( #&&&&&&&&&&&&&##%&&&            #
#       *&&#    &&&&&&&&&&&&&&    #&&&&&&&&&&&&&&&&#&#            #
#            &&%###&&&&&&&&&&/  #%         &&&&*#&&&&&( ,         #
#             #&&&&&&&&&&&&&&,           #&&&&&  #%&&&&# &        #
#            &&    #&&&&&&&&&#                #&&###&&&&&&        #
#           &     #&&&&&&&&&&&                  #&&&##&&&&        #
#                &&&&&&&&&&&&&&                  #&&&#&           #
#               %%.#%%&&&%&&&&&&#                 &&              #
#                  /%%%%%##%%%%%%%%%%#            #               #
#                   ## ###/ #### ####%%#                          #
#                     #   ##   ####  ######.                      #
##################### github.com/PivotTheNet ######################
##################### PivotTheNet.github.io #######################
###################### CREATED BY revsh3ll ########################