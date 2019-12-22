SQLITE_BINARY=sqlite3
SQLITE_DB=botman.sqlite

for word_rowid in "$@"
do
	WORD_VALUE=$("$SQLITE_BINARY" "$SQLITE_DB" "SELECT word FROM words WHERE rowid = $word_rowid;")
	if [[ ! -z $WORD_VALUE ]]; then
		"$SQLITE_BINARY" "$SQLITE_DB" "DELETE FROM seqs WHERE seqs.nextword = $word_rowid;"
		"$SQLITE_BINARY" "$SQLITE_DB" "DELETE FROM seqs WHERE seqs.prevword = $word_rowid;"
		"$SQLITE_BINARY" "$SQLITE_DB" "DELETE FROM words WHERE rowid = $word_rowid;"
		echo "Deleted $WORD_VALUE"
	fi
done
