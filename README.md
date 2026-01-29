# HomelabScripts

audiotoemby.py: Used for migrating listening sessions from AudioBookShelf to Emby Playback Reporting Plugin.

fastmigrateplayback.py: Used to add entries from another Emby Server Playback Reporting Plugin to a target Emby Server, I run 2 different instances of Emby and find this useful to have all watch data on one server.

fixItemID.py: Used to fix ItemID field in the Playback Reporting Plugin DB, itemID is calculated per server, so entries on the db from old servers or from other servers will not have correct itemID and links to media don't work properly.