# from scholarly import scholarly

# name = "Andrew Ng"  # 这里填你要查的人名
# search_query = scholarly.search_author(name)

# author = next(search_query)  # 拿到第一个匹配结果
# author = scholarly.fill(author)  # 补全信息（引用量、论文列表等）

# print("Name:", author["name"])
# print("Affiliation:", author["affiliation"])
# print("Total citations:", author["citedby"])

# from semanticscholar import SemanticScholar

# sch = SemanticScholar()

# # 直接按人名搜索
# author = sch.search_author("Andrew Ng")[0]
# author_id = author["authorId"]

# # 再拉取作者信息
# info = sch.get_author(author_id)

# print("Name:", info["name"])
# print("Citation count:", info["citationCount"])
from scholarly import scholarly

# Retrieve the author's data, fill-in, and print
# Get an iterator for the author results
search_query = scholarly.search_author("Steven A Cholewiak")
# Retrieve the first result from the iterator
first_author_result = next(search_query)
scholarly.pprint(first_author_result)

# Retrieve all the details for the author
author = scholarly.fill(first_author_result)
scholarly.pprint(author)

# Take a closer look at the first publication
first_publication = author["publications"][0]
first_publication_filled = scholarly.fill(first_publication)
scholarly.pprint(first_publication_filled)

# Print the titles of the author's publications
publication_titles = [pub["bib"]["title"] for pub in author["publications"]]
print(publication_titles)

# Which papers cited that publication?
citations = [
    citation["bib"]["title"] for citation in scholarly.citedby(first_publication_filled)
]
print(citations)
