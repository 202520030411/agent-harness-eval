from terminus2_patches.helpers import extract_deliverables

def test_extract_deliverables():
    ins = "The file chess_board.png has an image. Write the best move to /app/move.txt in the form e2e4."
    assert extract_deliverables(ins) == ["/app/move.txt"]
    ins2 = "I have provided a file a.out. Write me a program extract.js that, when run with `node extract.js /app/a.out > out.json` ..."
    d = extract_deliverables(ins2)
    assert "/app/a.out" not in d and "/app/extract.js" in d
    ins3 = "Put the function in a file called `/app/run.py` so that it can be imported. Output the fasta file titled primers.fasta."
    d3 = extract_deliverables(ins3)
    assert "/app/run.py" in d3 and "/app/primers.fasta" in d3
