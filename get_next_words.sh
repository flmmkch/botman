SQLITE_BINARY=sqlite3
SQLITE_DB=botman.sqlite

for word_rowid in "$@"
do
	"$SQLITE_BINARY" "$SQLITE_DB"  "SELECT words0.word, seqs.nextword, words1.word FROM seqs LEFT JOIN words AS words0 ON words0.rowid = seqs.prevword LEFT JOIN words AS words1 ON words1.rowid = seqs.nextword WHERE seqs.prevword = $word_rowid"
done

