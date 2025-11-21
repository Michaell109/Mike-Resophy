import urllib.request

import arxiv

# Construct the default API client
client = arxiv.Client()

# Define the paper title you want to search for
paper_title = "Scholar Inbox: Personalized Paper Recommendations for Scientists"

# Create a search object targeting the title field
search = arxiv.Search(
    query=f'ti:"{paper_title}"',  # Use f-string for easy title insertion, and quotes for exact phrase matching
    max_results=1,  # Assuming you expect a single, exact match
)

# Fetch the results
results = client.results(search)

# Iterate over the results (or get the first one if only one is expected)
try:
    first_result = next(results)
    print(f"Title: {first_result.title}")
    print(f"Summary:{first_result.summary}")
    print(f"Authors: {', '.join([author.name for author in first_result.authors])}")
    print(f"Abstract: {first_result.summary}")
    print(f"Published: {first_result.published}")
    print(f"ArXiv ID: {first_result.entry_id.split('/')[-1]}")
    paper_id = first_result.entry_id.split("/")[-1]

    # 直接访问 arXiv 的 BibTeX 接口
    bibtex_url = f"https://arxiv.org/bibtex/{paper_id}"
    with urllib.request.urlopen(bibtex_url) as response:
        bibtex_content = response.read().decode("utf-8")

    print(f"Title: {first_result.title}")
    print("\n--- Fetched BibTeX from arXiv ---")
    print(bibtex_content)

except StopIteration:
    print("Paper not found.")
except Exception as e:
    print(f"Error fetching BibTeX: {e}")
